"""Data retention and audit export (openspec 2026-11-11-enterprise-saas E7).

Retention: for an enterprise with ``enterprise_policies.retention_days``, a session untouched for longer than that
(and without a Run that is queued, running or waiting) has its content removed: messages, the events of its Runs and
its artifacts (rows marked deleted, stored copies deleted). The session row stays as an empty shell with status
``purged`` so Runs, usage, audit and channel bindings that point at it remain consistent; a purged session cannot
take new Runs because submission requires ``active``. Rows are removed rather than rewritten, so nothing of the
content survives in the database.

Audit export: the enterprise's audit records of a period as JSON lines, oldest first. Each line carries
``prev_hash`` and ``hash = sha256(prev_hash + canonical record)``, starting from ``sha256("nexus-audit:" + tenant)``,
so a reader can detect a line that was changed, removed or reordered in the exported file. The chain is computed at
export time; it does not protect the database rows themselves.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from nexus_core.platform import Principal, utc_now
from nexus_platform.authz.audit import audit
from nexus_platform.authz.permissions import require_api_permission
from nexus_platform.identity.service import require_membership, require_tenant, resolve_user
from nexus_platform.persistence.models import (ArtifactRecord, AuditRecord, EnterprisePolicyRecord, MessageRecord,
                                               RunEventRecord, RunRecord, SessionRecord)

BUSY = ('queued', 'running', 'waiting_input', 'waiting_approval')
PURGED = 'purged'


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def expired_sessions(db: Session, tenant_id: UUID, retention_days: int, *, now: datetime | None = None,
                     limit: int = 200) -> list[UUID]:
    cutoff = (now or utc_now()) - timedelta(days=retention_days)
    rows = db.scalars(select(SessionRecord).where(SessionRecord.tenant_id == tenant_id,
                                                  SessionRecord.status != PURGED)
                      .order_by(SessionRecord.updated_at).limit(limit * 4)).all()
    result = []
    for row in rows:
        if _aware(row.updated_at) >= cutoff:
            continue
        if db.scalar(select(RunRecord.id).where(RunRecord.session_id == row.id, RunRecord.status.in_(BUSY)).limit(1)):
            continue
        result.append(row.id)
        if len(result) >= limit:
            break
    return result


def purge_session(db: Session, session_id: UUID, root: Path | None = None) -> list[Path]:
    """Remove one session's content inside the caller's transaction; returns stored artifact files to delete."""
    from nexus_platform.artifacts.service import artifacts_root
    session = db.get(SessionRecord, session_id)
    run_ids = select(RunRecord.id).where(RunRecord.session_id == session_id)
    db.execute(delete(RunEventRecord).where(RunEventRecord.run_id.in_(run_ids)))
    db.execute(delete(MessageRecord).where(MessageRecord.session_id == session_id))
    root = (root or artifacts_root()).resolve()
    files = []
    now = utc_now()
    for artifact in db.scalars(select(ArtifactRecord).where(ArtifactRecord.session_id == session_id,
                                                           ArtifactRecord.deleted_at.is_(None))):
        artifact.deleted_at = now
        path = (root / artifact.storage_key).resolve()
        if root in path.parents:
            files.append(path)
    session.status, session.title, session.updated_at = PURGED, '', now
    return files


def run_retention(db: Session, *, now: datetime | None = None, root: Path | None = None) -> dict[str, int]:
    """Purge expired sessions of every enterprise that set a retention period; files are deleted after commit."""
    stats: dict[str, int] = {}
    files: list[Path] = []
    with db.begin():
        policies = db.scalars(select(EnterprisePolicyRecord).where(
            EnterprisePolicyRecord.retention_days.is_not(None))).all()
        for policy in policies:
            expired = expired_sessions(db, policy.tenant_id, policy.retention_days, now=now)
            for session_id in expired:
                files += purge_session(db, session_id, root)
            if expired:
                stats[str(policy.tenant_id)] = len(expired)
                from nexus_platform.persistence.models import TenantRecord
                audit(db, policy.tenant_id, db.get(TenantRecord, policy.tenant_id).created_by,
                      'retention.sessions_purged', 'tenant', str(policy.tenant_id),
                      {'sessions': len(expired), 'retention_days': policy.retention_days, 'by': 'retention'})
    for path in files:
        path.unlink(missing_ok=True)
    return stats


# ---------------------------------------------------------------------------------------------- audit export

def _genesis(tenant_id: UUID) -> str:
    return hashlib.sha256(f'nexus-audit:{tenant_id}'.encode()).hexdigest()


def _record(row: AuditRecord) -> dict[str, Any]:
    return {'id': str(row.id), 'created_at': _aware(row.created_at).isoformat(), 'actor_user_id': str(row.actor_user_id),
            'action': row.action, 'target_type': row.target_type, 'target_id': row.target_id,
            'result': row.result, 'metadata': row.metadata_json}


def export_lines(db: Session, principal: Principal, tenant_id: UUID, *, start: datetime, end: datetime
                 ) -> Iterator[str]:
    """JSON lines of the period, hash-chained; needs ``audit:read``. The export itself is audited first."""
    with db.begin():
        user = resolve_user(db, principal)
        require_tenant(db, tenant_id)
        require_membership(db, tenant_id, user.id)
        require_api_permission(db, tenant_id, user.id, 'audit:read')
        audit(db, tenant_id, user.id, 'audit.exported', 'tenant', str(tenant_id),
              {'start': start.isoformat(), 'end': end.isoformat()})
    with db.begin():
        rows = db.scalars(select(AuditRecord).where(AuditRecord.tenant_id == tenant_id,
                                                   AuditRecord.created_at >= start, AuditRecord.created_at < end)
                          .order_by(AuditRecord.created_at, AuditRecord.id)).all()
        records = [_record(row) for row in rows]
    previous = _genesis(tenant_id)
    for record in records:
        canonical = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        digest = hashlib.sha256((previous + canonical).encode()).hexdigest()
        yield json.dumps({**record, 'prev_hash': previous, 'hash': digest}, ensure_ascii=False) + '\n'
        previous = digest


def verify_lines(tenant_id: UUID, lines: list[str]) -> bool:
    """Check an exported file: every line's hash follows from the previous one."""
    previous = _genesis(tenant_id)
    for line in lines:
        item = json.loads(line)
        claimed, prev = item.pop('hash'), item.pop('prev_hash')
        canonical = json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        if prev != previous or hashlib.sha256((previous + canonical).encode()).hexdigest() != claimed:
            return False
        previous = claimed
    return True


def day_bounds(start, end) -> tuple[datetime, datetime]:
    """Whole days, in UTC, from ``start`` through ``end`` (inclusive)."""
    return (datetime.combine(start, time.min, tzinfo=timezone.utc),
            datetime.combine(end + timedelta(days=1), time.min, tzinfo=timezone.utc))
