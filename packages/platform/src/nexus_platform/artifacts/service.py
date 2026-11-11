"""Registering, listing, downloading and deleting sandbox artifacts (openspec 2026-11-07-tool-expansion 4.6, design 2.6).

When a Run ends, the files under `/outputs` are copied to the artifact root and recorded, so what a person downloads
later is the file as the Run left it. Authorization follows the session: its owner reaches the artifacts of their
own sessions, a space owner or admin reaches every artifact of the space, anyone else gets "not found".

Copies happen outside the database transaction (they can be large); rows, the run event and the audit record are
written together afterwards. A registration failure never changes how the Run ended; the worker only logs it.
"""
from __future__ import annotations

import hashlib
import mimetypes
import os
import stat
from pathlib import Path
from typing import Iterable
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from nexus_core.platform import Principal, new_id, utc_now
from nexus_platform.authz.audit import audit
from nexus_platform.errors import NotFound
from nexus_platform.identity.service import require_membership, require_tenant, resolve_user
from nexus_platform.orgs.access import is_space_manager
from nexus_platform.persistence.models import ArtifactRecord, SessionRecord
from nexus_platform.runs.events import append_event

ARTIFACT_DIR = '_artifacts'
MAX_FILE_BYTES = 50 * 1024 * 1024
MAX_FILES_PER_RUN = 50
MAX_RUN_BYTES = 200 * 1024 * 1024
TENANT_QUOTA_BYTES = 2 * 1024 ** 3
LIST_MAX = 200
_CHUNK = 1024 * 1024
#: Types the platform's mime table may not know; everything else is guessed from the name.
_MIME = {'.md': 'text/markdown', '.csv': 'text/csv', '.json': 'application/json', '.log': 'text/plain'}


def artifacts_root() -> Path:
    """`<[sandbox].workspace_root>/_artifacts`. The sandbox section is read even when the sandbox is switched off, so
    artifacts made earlier stay downloadable. Raises DeploymentConfigError when the section is invalid."""
    from nexus_sandbox.settings import load_config
    return Path(load_config().workspace_root).resolve() / ARTIFACT_DIR


def _mime(path: str) -> str:
    suffix = os.path.splitext(path)[1].lower()
    return _MIME.get(suffix) or mimetypes.guess_type(path)[0] or 'application/octet-stream'


def _view(row: ArtifactRecord) -> dict:
    return {'id': str(row.id), 'session_id': str(row.session_id), 'run_id': str(row.run_id), 'name': row.name,
            'path': row.path, 'size': row.size, 'sha256': row.sha256, 'mime': row.mime,
            'created_at': row.created_at.isoformat()}


def _copy(source: Path, destination: Path) -> tuple[str, int]:
    """Copy a regular file without following symlinks and return (sha256, size). Raises ValueError when the file is
    not a regular file or grows past :data:`MAX_FILE_BYTES` while being read."""
    flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0)
    descriptor = os.open(source, flags)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError('not_regular')
        digest, total = hashlib.sha256(), 0
        destination.parent.mkdir(parents=True, exist_ok=True)
        with os.fdopen(os.dup(descriptor), 'rb') as stream, open(destination, 'wb') as target:
            while chunk := stream.read(_CHUNK):
                total += len(chunk)
                if total > MAX_FILE_BYTES:
                    raise ValueError('too_large')
                digest.update(chunk)
                target.write(chunk)
        return digest.hexdigest(), total
    except BaseException:
        destination.unlink(missing_ok=True)
        raise
    finally:
        os.close(descriptor)


def register_run_outputs(db: Session, *, tenant_id: UUID, session_id: UUID, run_id: UUID, owner_user_id: UUID,
                         files: Iterable[tuple[str, Path, int]], root: Path | None = None) -> dict:
    """Copy and record the files a Run left under `/outputs`.

    ``files`` is what the sandbox session lists: (virtual path, host path, size). Files over the limits and files
    unchanged since the previous registration in this session are skipped, each with a reason. Returns
    ``{'registered': [view, ...], 'skipped': [{'path', 'reason'}, ...]}``.
    """
    root = root or artifacts_root()
    listed = sorted(files, key=lambda item: item[0])
    with db.begin():
        used = db.scalar(select(func.coalesce(func.sum(ArtifactRecord.size), 0)).where(
            ArtifactRecord.tenant_id == tenant_id, ArtifactRecord.deleted_at.is_(None))) or 0
        latest: dict[str, str] = {}
        for path, sha in db.execute(select(ArtifactRecord.path, ArtifactRecord.sha256).where(
                ArtifactRecord.session_id == session_id, ArtifactRecord.deleted_at.is_(None))
                .order_by(ArtifactRecord.created_at)):
            latest[path] = sha  # ordered by time, so the last one wins
    registered: list[ArtifactRecord] = []
    skipped: list[dict] = []
    run_bytes = 0
    for path, host, size in listed:
        reason = ''
        if size > MAX_FILE_BYTES:  # a file that can never be kept is reported as such, whatever the counts are
            reason = 'too_large'
        elif len(registered) >= MAX_FILES_PER_RUN:
            reason = 'too_many'
        elif run_bytes + size > MAX_RUN_BYTES:
            reason = 'run_quota'
        elif used + run_bytes + size > TENANT_QUOTA_BYTES:
            reason = 'tenant_quota'
        if reason:
            skipped.append({'path': path, 'reason': reason})
            continue
        artifact_id = new_id()
        key = f'{tenant_id}/{artifact_id}'
        try:
            sha, written = _copy(host, root / key)
        except (OSError, ValueError) as error:
            skipped.append({'path': path, 'reason': str(error) if isinstance(error, ValueError) else 'unreadable'})
            continue
        if latest.get(path) == sha:
            (root / key).unlink(missing_ok=True)
            skipped.append({'path': path, 'reason': 'unchanged'})
            continue
        run_bytes += written
        registered.append(ArtifactRecord(
            id=artifact_id, tenant_id=tenant_id, session_id=session_id, run_id=run_id, owner_user_id=owner_user_id,
            path=path, name=path.rsplit('/', 1)[-1][:255], size=written, sha256=sha,
            mime=_mime(path), storage_key=key, created_at=utc_now()))
    if registered or skipped:
        with db.begin():
            db.add_all(registered)
            db.flush()
            summary = {'ids': [str(row.id) for row in registered], 'count': len(registered), 'skipped': skipped}
            append_event(db, run_id, 'artifacts.registered', summary)
            if registered:
                audit(db, tenant_id, owner_user_id, 'artifact.registered', 'run', str(run_id),
                      {'count': len(registered), 'skipped': len(skipped), 'bytes': run_bytes})
    return {'registered': [_view(row) for row in registered], 'skipped': skipped}


# ---------------------------------------------------------------- reading (authorized)

def _reader(db: Session, principal: Principal, tenant_id: UUID):
    """(user id, whether the person manages the space) of an active member; anyone else raises."""
    user = resolve_user(db, principal)
    require_tenant(db, tenant_id)
    require_membership(db, tenant_id, user.id)
    return user.id, is_space_manager(db, tenant_id, user.id)


def _visible(tenant_id: UUID, user_id: UUID, manager: bool):
    query = select(ArtifactRecord).join(SessionRecord, SessionRecord.id == ArtifactRecord.session_id).where(
        ArtifactRecord.tenant_id == tenant_id, ArtifactRecord.deleted_at.is_(None))
    return query if manager else query.where(SessionRecord.owner_user_id == user_id)


def _one(db: Session, tenant_id: UUID, user_id: UUID, manager: bool, artifact_id: UUID) -> ArtifactRecord:
    row = db.scalar(_visible(tenant_id, user_id, manager).where(ArtifactRecord.id == artifact_id))
    if row is None:
        raise NotFound('Artifact not found')
    return row


def list_artifacts(db: Session, principal: Principal, tenant_id: UUID, *, session_id: UUID | None = None,
                   run_id: UUID | None = None, limit: int = 50, offset: int = 0) -> list[dict]:
    """Artifacts the caller may see, newest first, optionally of one session or Run."""
    with db.begin():
        user_id, manager = _reader(db, principal, tenant_id)
        query = _visible(tenant_id, user_id, manager)
        if session_id is not None:
            query = query.where(ArtifactRecord.session_id == session_id)
        if run_id is not None:
            query = query.where(ArtifactRecord.run_id == run_id)
        rows = db.scalars(query.order_by(ArtifactRecord.created_at.desc(), ArtifactRecord.path)
                          .limit(max(1, min(limit, LIST_MAX))).offset(max(0, offset))).all()
        return [_view(row) for row in rows]


def get_artifact(db: Session, principal: Principal, tenant_id: UUID, artifact_id: UUID) -> dict:
    with db.begin():
        user_id, manager = _reader(db, principal, tenant_id)
        return _view(_one(db, tenant_id, user_id, manager, artifact_id))


def open_artifact(db: Session, principal: Principal, tenant_id: UUID, artifact_id: UUID,
                  root: Path | None = None) -> tuple[dict, Path]:
    """Authorize a download, audit it, and return (view, path of the stored copy)."""
    root = (root or artifacts_root()).resolve()
    with db.begin():
        user_id, manager = _reader(db, principal, tenant_id)
        row = _one(db, tenant_id, user_id, manager, artifact_id)
        stored = (root / row.storage_key).resolve()
        if root not in stored.parents or stored.is_symlink() or not stored.is_file():
            raise NotFound('Artifact file is no longer available')
        audit(db, tenant_id, user_id, 'artifact.downloaded', 'artifact', str(row.id), {'run_id': str(row.run_id)})
        return _view(row), stored


def delete_artifact(db: Session, principal: Principal, tenant_id: UUID, artifact_id: UUID,
                    root: Path | None = None) -> None:
    """Remove an artifact the caller may see: the row is marked deleted and the stored copy is deleted."""
    root = (root or artifacts_root()).resolve()
    with db.begin():
        user_id, manager = _reader(db, principal, tenant_id)
        row = _one(db, tenant_id, user_id, manager, artifact_id)
        row.deleted_at = utc_now()
        stored = (root / row.storage_key).resolve()
        audit(db, tenant_id, user_id, 'artifact.deleted', 'artifact', str(row.id), {'run_id': str(row.run_id)})
    if root in stored.parents:
        stored.unlink(missing_ok=True)
