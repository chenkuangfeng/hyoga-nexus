"""Durable execution messages; model execution stays in runtimes."""
from __future__ import annotations
from dataclasses import asdict
from uuid import UUID
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from nexus_core.platform import new_id, utc_now
from nexus_core.runtime import ModelMessage
from nexus_platform.errors import PlatformError
from nexus_platform.persistence.models import MessageRecord, RunRecord, SessionRecord
from nexus_platform.authz.resources import authorize_resource
from .domain import Run


from nexus_platform.sessions.snapshot import advance


def add_message(db: Session, run: RunRecord | Run, message: ModelMessage, *, origin: str = "runtime") -> MessageRecord:
    session_row = db.scalar(select(SessionRecord).where(SessionRecord.id == run.session_id).with_for_update())
    session_row.updated_at = utc_now()
    advance(db, run.session_id)
    sequence = db.scalar(select(func.coalesce(func.max(MessageRecord.sequence), 0)).where(
        MessageRecord.session_id == run.session_id)) + 1
    row = MessageRecord(id=new_id(), session_id=run.session_id, run_id=run.id, sequence=sequence,
        role=message.role, content=message.content, created_at=utc_now(),
        runtime_metadata={'origin': origin, 'tool_calls': [asdict(call) for call in message.tool_calls],
                          'tool_call_id': message.tool_call_id})
    db.add(row)
    return row


def _grant_allowed(db: Session, key: tuple) -> bool:
    """One resource grant check; a failed check is a denial, not an error."""
    tenant_id, kind, resource_id, source_tenant_id, version_id = key
    try:
        authorize_resource(db, tenant_id, kind, resource_id, source_tenant_id=UUID(source_tenant_id),
                           resource_version_id=version_id, permission='use')
        return True
    except PlatformError:
        return False


def histories_allowed(db: Session, runs) -> dict[UUID, bool]:
    """Decide history visibility for many Runs with one check per distinct resource grant (P8).

    A Run's history is visible only if every resource in its snapshot is still granted. Grants are
    read from the database on every call, so revocation takes effect on the next preparation; only
    the repeated checks for the same grant within one call are merged.
    """
    decisions: dict[tuple, bool] = {}
    results: dict[UUID, bool] = {}
    for run in runs:
        allowed = True
        for resource in run.config_snapshot.get('resources', []):
            key = (run.tenant_id, resource['kind'], resource['resource_id'], resource['source_tenant_id'],
                   resource.get('resource_version_id'))
            if key not in decisions:
                decisions[key] = _grant_allowed(db, key)
            if not decisions[key]:
                allowed = False
                break
        results[run.id] = allowed
    return results


def _history_allowed(db: Session, run: RunRecord) -> bool:
    return histories_allowed(db, [run])[run.id]
