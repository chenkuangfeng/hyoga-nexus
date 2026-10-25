"""Run cancellation: one application responsibility with legacy function compatibility."""
from __future__ import annotations
from nexus_platform.persistence.unit_of_work import SqlAlchemyUnitOfWork
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.orm import Session
from nexus_core.platform import Principal, RunStatus, new_id, utc_now
from nexus_platform.errors import NotFound
from nexus_platform.identity.service import require_membership, require_workspace, resolve_user
from nexus_platform.persistence.models import OutboxRecord, RunRecord
from nexus_platform.workspaces.service import audit
from .state import transition_run
from .events import append_event

def request_cancel(session: Session, principal: Principal, workspace_id: UUID, run_id: UUID) -> RunRecord:
    return RunCancellationService(SqlAlchemyUnitOfWork(session)).cancel(principal, workspace_id, run_id)

class RunCancellationService:
    """Own the cancellation application operation and its transaction boundary."""

    def __init__(self, unit_of_work: SqlAlchemyUnitOfWork):
        self.unit_of_work = unit_of_work

    def cancel(self, principal: Principal, workspace_id: UUID, run_id: UUID) -> RunRecord:
        now = utc_now()
        with self.unit_of_work as work:
            session = work.session
            user = resolve_user(session, principal)
            require_workspace(session, workspace_id)
            require_membership(session, workspace_id, user.id)
            run = session.scalar(
                select(RunRecord).where(
                    RunRecord.id == run_id,
                    RunRecord.workspace_id == workspace_id,
                    RunRecord.principal_id == user.id,
                ).with_for_update()
            )
            if run is None:
                raise NotFound("Run not found")
            if RunStatus(run.status).terminal:
                return run
            if run.status in (RunStatus.QUEUED.value, RunStatus.WAITING_INPUT.value, RunStatus.WAITING_APPROVAL.value):
                transition_run(run, RunStatus.CANCELLED)
                run.cancel_requested_at = now
                run.ended_at = now
                for task in session.scalars(
                    select(OutboxRecord).where(OutboxRecord.run_id == run.id, OutboxRecord.completed_at.is_(None))
                ):
                    task.completed_at = now
                append_event(session, run.id, "run.cancelled", {"status": run.status}, now)
            else:
                run.cancel_requested_at = now
                existing_cancel = session.scalar(
                    select(OutboxRecord).where(
                        OutboxRecord.run_id == run.id,
                        OutboxRecord.message_type == "run.cancel",
                        OutboxRecord.completed_at.is_(None),
                    )
                )
                if existing_cancel is None:
                    session.add(
                        OutboxRecord(
                            id=new_id(), run_id=run.id, message_type="run.cancel", payload={"run_id": str(run.id)},
                            available_at=now, attempts=0, created_at=now,
                        )
                    )
            append_event(session, run.id, "run.cancel_requested", {"status": run.status}, now)
            audit(session, workspace_id, user.id, "run.cancel_requested", "run", str(run.id))
        return run
