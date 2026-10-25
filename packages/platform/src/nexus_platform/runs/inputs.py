"""Durable execution inputs; model execution stays in runtimes."""
from __future__ import annotations
from nexus_platform.persistence.unit_of_work import SqlAlchemyUnitOfWork
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.orm import Session
from nexus_core.platform import Principal, utc_now
from nexus_core.runtime import ModelMessage
from nexus_platform.errors import Conflict, NotFound
from nexus_platform.identity.service import require_membership, require_workspace, resolve_user
from nexus_platform.persistence.models import InputRequestRecord, OutboxRecord, RunRecord
from nexus_platform.runs.service import append_event
from nexus_platform.workspaces.service import audit
from .messages import add_message

def respond_input(db: Session, principal: Principal, workspace_id: UUID, run_id: UUID, input_request_id: UUID, response: str, key: str) -> RunRecord:
    return RunInputService(SqlAlchemyUnitOfWork(db)).respond(principal, workspace_id, run_id, input_request_id, response, key)

class RunInputService:
    """Own the inputs application operation and its transaction boundary."""

    def __init__(self, unit_of_work: SqlAlchemyUnitOfWork):
        self.unit_of_work = unit_of_work

    def respond(self, principal: Principal, workspace_id: UUID, run_id: UUID,
                      input_request_id: UUID, response: str, key: str) -> RunRecord:
        if not key.strip() or len(key) > 255:
            raise ValueError('Idempotency-Key must contain 1 to 255 characters')
        with self.unit_of_work as work:
            db = work.session
            user = resolve_user(db, principal)
            require_workspace(db, workspace_id)
            require_membership(db, workspace_id, user.id)
            run = db.scalar(select(RunRecord).where(RunRecord.id == run_id,
                RunRecord.workspace_id == workspace_id, RunRecord.principal_id == user.id).with_for_update())
            if not run:
                raise NotFound('Run not found')
            request = db.get(InputRequestRecord, input_request_id)
            if not request or request.run_id != run.id:
                raise NotFound('Input request not found')
            if request.responded_at:
                if request.response_key != key or request.response != response:
                    raise Conflict('Input request already consumed')
                return run
            if run.status != 'waiting_input' or run.cancel_requested_at:
                raise Conflict('Run is not waiting for input')
            request.response, request.response_key, request.responded_at = response, key, utc_now()
            add_message(db, run, ModelMessage('user', response), origin='user_input')
            append_event(db, run.id, 'input.received', {'input_request_id': str(request.id)})
            task = db.scalar(select(OutboxRecord).where(OutboxRecord.run_id == run.id,
                OutboxRecord.message_type == 'run.execute').with_for_update())
            task.completed_at, task.lease_owner, task.lease_until, task.available_at = None, None, None, utc_now()
            audit(db, workspace_id, user.id, 'input.received', 'run', str(run.id))
            return run
