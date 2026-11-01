"""Session state snapshot: versioned, data-only JSON guarded by an optimistic watermark.

Rules (see docs/architecture.md 2.12):
- The snapshot holds plain JSON data only: no handles, clients, model objects or secrets.
- ``watermark`` starts at 0 and increases by one on every successful save. A save names the
  watermark it read; the conditional UPDATE matches only that value, so a concurrent writer
  makes the save fail with ``WatermarkConflict`` instead of silently overwriting.
- ``snapshot_version`` selects the decoder. Only versions in ``MIGRATIONS`` plus
  ``SNAPSHOT_VERSION`` are accepted; anything else is refused rather than guessed.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any
from uuid import UUID

from sqlalchemy import update
from sqlalchemy.orm import Session

from nexus_platform.errors import Conflict, NotFound, PlatformError
from nexus_platform.persistence.models import SessionRecord

SNAPSHOT_VERSION = 2
#: Upper bound on the encoded size of one snapshot; larger state belongs in events or artifacts.
MAX_SNAPSHOT_BYTES = 1024 * 1024


class WatermarkConflict(Conflict):
    """The session changed since the caller read it; the caller must reload and retry."""
    code = "session_watermark_conflict"


class UnknownSnapshotVersion(PlatformError):
    """The stored snapshot version has no decoder; it is refused, never guessed."""
    code = "unknown_snapshot_version"


class InvalidSnapshot(ValueError):
    """The payload is not plain JSON data or exceeds the size bound."""


#: Decoders from an older stored version to the current shape. Empty until an older version
#: has been persisted; a version without an entry here is refused by ``decode``.
MIGRATIONS: dict[int, Callable[[dict[str, Any]], dict[str, Any]]] = {}


def validate(payload: Any) -> dict[str, Any]:
    """Return ``payload`` if it is a JSON object within the size bound; raise InvalidSnapshot otherwise."""
    if not isinstance(payload, dict):
        raise InvalidSnapshot("snapshot must be a JSON object")
    try:
        encoded = json.dumps(payload, allow_nan=False, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise InvalidSnapshot(f"snapshot is not plain JSON data: {exc}") from exc
    if len(encoded.encode("utf-8")) > MAX_SNAPSHOT_BYTES:
        raise InvalidSnapshot("snapshot exceeds the size bound")
    return payload


def decode(version: int | None, payload: dict[str, Any] | None) -> dict[str, Any] | None:
    """Bring a stored snapshot to the current shape, or refuse an unknown version."""
    if payload is None or version is None:
        return None
    if version == SNAPSHOT_VERSION:
        return payload
    migrate = MIGRATIONS.get(version)
    if migrate is None:
        raise UnknownSnapshotVersion(f"snapshot version {version} is not supported")
    return validate(migrate(payload))


def read(db: Session, session_id: UUID) -> tuple[int, dict[str, Any] | None]:
    """Return ``(watermark, decoded snapshot)``. The watermark is the token for the next save."""
    row = db.get(SessionRecord, session_id)
    if row is None:
        raise NotFound("session not found")
    return row.watermark, decode(row.snapshot_version, row.snapshot)


def save(db: Session, session_id: UUID, *, expected_watermark: int, payload: dict[str, Any]) -> int:
    """Store ``payload`` if the session is still at ``expected_watermark``; return the new watermark.

    Runs inside the caller's transaction and does not commit. The guard is a conditional UPDATE
    whose rowcount must be 1, which holds on SQLite and PostgreSQL alike and does not depend on
    row locks.
    """
    data = validate(payload)
    result = db.execute(
        update(SessionRecord)
        .where(SessionRecord.id == session_id, SessionRecord.watermark == expected_watermark)
        .values(watermark=expected_watermark + 1, snapshot=data, snapshot_version=SNAPSHOT_VERSION)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        raise WatermarkConflict(f"session {session_id} is not at watermark {expected_watermark}")
    db.flush()
    return expected_watermark + 1
