"""Durable GA intervene/keyinfo translated from WeKnora steer's persist-before-consume flow."""
from uuid import UUID
from sqlalchemy import select
from nexus_core.platform import new_id, utc_now
from nexus_core.runtime import ModelMessage
from nexus_platform.models.provider_settings import context
from nexus_platform.persistence.models import RunRecord, RunDirectiveRecord
from nexus_platform.errors import NotFound, Conflict
from nexus_platform.authz.audit import audit
from nexus_platform.runs.service import append_event


def submit(db, principal, tenant_id, run_id, content: str, key: str):
    """Append a correction to the owner's active Run; duplicate keys cannot change content."""
    if not content.strip() or len(content) > 8000 or not key.strip() or len(key) > 255:
        raise ValueError('Correction and idempotency key are required within size limits')
    with db.begin():
        user, _ = context(db, principal, tenant_id)
        run = db.scalar(select(RunRecord).where(RunRecord.id == run_id,
            RunRecord.tenant_id == tenant_id, RunRecord.principal_id == user.id).with_for_update())
        if not run:
            raise NotFound('Run not found')
        previous = db.scalar(select(RunDirectiveRecord).where(RunDirectiveRecord.run_id == run_id, RunDirectiveRecord.idempotency_key == key))
        if previous:
            if previous.content != content:
                raise Conflict('Idempotency key already has another correction')
            return previous
        # Confirmed busy-queue rule: a queued Run may only be cancelled, so corrections are accepted only while running.
        if run.status != 'running' or run.cancel_requested_at:
            raise Conflict('Run is not accepting corrections')
        row = RunDirectiveRecord(id=new_id(), run_id=run_id, principal_id=user.id, content=content,
                                 idempotency_key=key, created_at=utc_now())
        db.add(row)
        append_event(db, run_id, 'input.queued', {'directive_id': str(row.id)})
        audit(db, tenant_id, user.id, 'run.steered', 'run', str(run_id))
        return row


def consume(db, run, add_message):
    """Called inside the leased Run transaction; append and consume atomically in source order."""
    rows = db.scalars(select(RunDirectiveRecord).where(RunDirectiveRecord.run_id == run.id,
        RunDirectiveRecord.consumed_at.is_(None)).order_by(RunDirectiveRecord.created_at, RunDirectiveRecord.id).with_for_update())
    messages = []
    for row in rows:
        if row.principal_id != run.principal_id:
            raise Conflict('Correction principal mismatch')
        message = ModelMessage('user', row.content)
        add_message(db, run, message, origin='user_steer')
        row.consumed_at = utc_now()
        append_event(db, run.id, 'input.injected', {'directive_id': str(row.id)})
        messages.append(message)
    return messages
