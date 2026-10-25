"""Run leasing: one application responsibility with legacy function compatibility."""
from __future__ import annotations
from nexus_platform.persistence.unit_of_work import SqlAlchemyUnitOfWork
from datetime import timedelta
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.orm import Session
from nexus_core.platform import RunStatus, utc_now
from nexus_platform.persistence.models import OutboxRecord, RunRecord
from nexus_platform.workspaces.service import audit
from .state import transition_run
from .events import append_event
DEFAULT_LEASE_SECONDS = 60

def claim_next(session: Session, worker_id: str, *, lease_seconds: int=DEFAULT_LEASE_SECONDS) -> UUID | None:
    return RunLeaseService(SqlAlchemyUnitOfWork(session)).claim(worker_id, lease_seconds=lease_seconds)

def process_claimed(session: Session, task_id: UUID, worker_id: str) -> bool:
    return RunLeaseService(SqlAlchemyUnitOfWork(session)).process(task_id, worker_id)

class RunLeaseService:
    """Own the leasing application operation and its transaction boundary."""

    def __init__(self, unit_of_work: SqlAlchemyUnitOfWork):
        self.unit_of_work = unit_of_work

    def claim(self, worker_id: str, *, lease_seconds: int=DEFAULT_LEASE_SECONDS) -> UUID | None:
        now = utc_now()
        with self.unit_of_work as work:
            return work.outbox.claim(worker_id, now, now + timedelta(seconds=lease_seconds))


    def process(self, task_id: UUID, worker_id: str) -> bool:
        now = utc_now()
        with self.unit_of_work as work:
            session = work.session
            task = session.scalar(
                select(OutboxRecord).where(OutboxRecord.id == task_id).with_for_update()
            )
            if task is None or task.completed_at is not None or task.lease_owner != worker_id:
                return False
            run = session.scalar(select(RunRecord).where(RunRecord.id == task.run_id).with_for_update())
            if run is None:
                task.completed_at = now
                return True
            if RunStatus(run.status).terminal:
                task.completed_at = now
                return True
            if task.message_type == "run.cancel" or run.cancel_requested_at is not None:
                transition_run(run, RunStatus.CANCELLED)
                run.ended_at = now
                append_event(session, run.id, "run.cancelled", {"status": run.status}, now)
                audit(session, run.workspace_id, run.principal_id, "run.cancelled", "run", str(run.id))
            elif task.message_type == "run.execute":
                if run.status == RunStatus.RUNNING.value or run.attempt > 0:
                    transition_run(run, RunStatus.INTERRUPTED)
                    run.error_code = "worker_lease_expired"
                    run.error_message = "Worker lost the lease before the run reached a known outcome"
                    run.ended_at = now
                    append_event(session, run.id, "run.interrupted", {
                        "status": run.status, "error_code": run.error_code,
                    }, now)
                    audit(session, run.workspace_id, run.principal_id, "run.interrupted", "run", str(run.id),
                          {"error_code": run.error_code})
                else:
                    transition_run(run, RunStatus.RUNNING)
                    run.attempt += 1
                    run.started_at = now
                    append_event(session, run.id, "run.started", {"status": run.status}, now)
                    transition_run(run, RunStatus.FAILED)
                    run.error_code = "runtime_not_configured"
                    run.error_message = "P1 persists runs; no runtime executor is configured yet"
                    run.ended_at = now
                    append_event(session, run.id, "run.failed", {
                        "status": run.status, "error_code": run.error_code,
                    }, now)
                    audit(session, run.workspace_id, run.principal_id, "run.failed", "run", str(run.id),
                          {"error_code": run.error_code})
            task.completed_at = now
            task.lease_owner = None
            task.lease_until = None
        return True
