"""Per-session memory index snapshots (openspec 2026-11-01-memory-optimization, stage 2).

The published-memory index in the system prompt is frozen per session: the first Run stores it and every
later Run in that session reuses the stored text, so the prompt prefix does not change when memory changes.
New published entries reach the session only after an explicit refresh, which deletes the stored row.
Since openspec 2026-11-06-memory-evolution stage 2 the snapshot also carries a capacity line and the
bodies of `profile` entries (the resident block, at most 1000 characters); other bodies are still read
by ID through `read_memory`. The resident entries are stored with the snapshot so each Run can report
them in a `memory.used` event.

All functions take the caller's transaction and never commit.
"""
from __future__ import annotations

import hashlib
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus_core.platform import Principal, utc_now
from nexus_platform.authz.audit import audit
from nexus_platform.errors import NotFound
from nexus_platform.identity.service import require_membership, require_tenant, resolve_user
from nexus_platform.memory.repository import SqlMemoryRepository
from nexus_memory import service as memory_rules
from nexus_platform.persistence.models import SessionMemorySnapshotRecord, SessionRecord


def version_key(db: Session, tenant_id: UUID, owner_id: UUID) -> str:
    """Fingerprint of the owner's published entries (id, current version, enabled, validity end, kind,
    importance).

    Sorted so the key does not depend on query order. Changes when an entry is published, edited,
    disabled, given a validity end, moved to another kind or given another importance (both change the
    resident block or the index order); it is informational only and never refreshes a snapshot.
    """
    entries = SqlMemoryRepository(db).published_entries(tenant_id, owner_id, '')
    parts = sorted(
        f'{row.id}:{row.current_version}:{row.enabled}:{row.valid_until.isoformat() if row.valid_until else ""}'
        f':{row.kind}:{row.importance}'
        for row in entries
    )
    return hashlib.sha256('\n'.join(parts).encode('utf-8')).hexdigest()


def session_snapshot(db: Session, *, tenant_id: UUID, owner_id: UUID, session_id: UUID, project: str = '',
                     now: datetime | None = None, include_profile: bool = True) -> SessionMemorySnapshotRecord:
    """Return the session's frozen snapshot row, creating it on the first call (see `session_index`)."""
    row = db.get(SessionMemorySnapshotRecord, session_id)
    if row is not None and row.tenant_id == tenant_id and row.owner_user_id == owner_id:
        from types import SimpleNamespace
        from nexus_core.runtime.context import ContextDependency
        from nexus_platform.runs.context_access import sources_allowed
        scope = SimpleNamespace(tenant_id=tenant_id, principal_id=owner_id, config_snapshot={})
        if row.context_schema_version == 1 and row.context_dependencies is not None and sources_allowed(
                db, scope, [ContextDependency(**d) for d in row.context_dependencies]):
            return row
        # A legacy or unsafe snapshot must not keep deleted/private facts in its frozen text.
        db.delete(row)
        db.flush()
    built = memory_rules.snapshot(SqlMemoryRepository(db), tenant_id, owner_id, project,
                                   now=now or utc_now(), include_profile=include_profile)
    text = built.text
    # External snapshot hooks are collected by ContextPreparationService outside transactions.
    key = version_key(db, tenant_id, owner_id)
    row = SessionMemorySnapshotRecord(
        session_id=session_id, tenant_id=tenant_id, owner_user_id=owner_id,
        index_text=text, version_key=key, created_at=now or utc_now(),
        resident_entries=[dict(item) for item in built.resident],
        context_dependencies=list(built.dependencies), context_schema_version=1,
    )
    db.add(row)
    db.flush()
    audit(db, tenant_id, owner_id, 'memory.snapshot_created', 'session', str(session_id),
          {'version_key': key, 'resident': len(built.resident)})
    return row


def session_index(db: Session, *, tenant_id: UUID, owner_id: UUID, session_id: UUID, project: str = '',
                  now: datetime | None = None) -> str:
    """Return the session's frozen index, creating it on the first call.

    Called from the Run preparation path. Runs in one session are admitted one at a time, so two
    creators cannot race here; a duplicate would raise and abort the Run instead of corrupting the snapshot.
    """
    return session_snapshot(db, tenant_id=tenant_id, owner_id=owner_id, session_id=session_id,
                            project=project, now=now).index_text


def _owned_session(db: Session, principal: Principal, tenant_id: UUID, session_id: UUID):
    """The caller's own session in this space. Snapshots follow memory, which is owner-only, so space
    owners and admins do not get access here even though they can read the session list."""
    user = resolve_user(db, principal)
    require_tenant(db, tenant_id)
    require_membership(db, tenant_id, user.id)
    row = db.scalar(select(SessionRecord).where(
        SessionRecord.id == session_id, SessionRecord.tenant_id == tenant_id, SessionRecord.owner_user_id == user.id))
    if row is None:
        raise NotFound('Session not found')
    return user


def snapshot_status(db: Session, principal: Principal, tenant_id: UUID, session_id: UUID) -> dict:
    """Whether the session has a snapshot, when it was taken, and whether memory has changed since."""
    with db.begin():
        user = _owned_session(db, principal, tenant_id, session_id)
        row = db.get(SessionMemorySnapshotRecord, session_id)
        if row is None:
            return {'exists': False, 'created_at': None, 'stale': False}
        return {
            'exists': True,
            'created_at': row.created_at,
            'stale': row.version_key != version_key(db, tenant_id, user.id),
        }


def refresh_snapshot(db: Session, principal: Principal, tenant_id: UUID, session_id: UUID) -> None:
    """Delete the session's snapshot so the next Run builds one from current memory."""
    with db.begin():
        user = _owned_session(db, principal, tenant_id, session_id)
        row = db.get(SessionMemorySnapshotRecord, session_id)
        if row is not None:
            db.delete(row)
            db.flush()
        audit(db, tenant_id, user.id, 'memory.snapshot_refreshed', 'session', str(session_id), {})
