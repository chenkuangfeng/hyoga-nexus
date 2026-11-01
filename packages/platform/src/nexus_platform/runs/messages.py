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


def _history_allowed(db: Session, run: RunRecord) -> bool:
    try:
        for resource in run.config_snapshot.get('resources', []):
            authorize_resource(db, run.tenant_id, resource['kind'], resource['resource_id'],
                source_tenant_id=UUID(resource['source_tenant_id']),
                resource_version_id=resource.get('resource_version_id'), permission='use')
        return True
    except PlatformError:
        return False
