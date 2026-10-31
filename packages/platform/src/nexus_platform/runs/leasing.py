"""Run lease policy and the old P1 worker path; native execution remains in preparation/store."""
from __future__ import annotations
from datetime import timedelta
from typing import TYPE_CHECKING
from uuid import UUID
from nexus_core.platform import RunStatus, utc_now
from .command_ports import RunCommandUnitOfWork
from .state import transition_run

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

DEFAULT_LEASE_SECONDS = 60


def claim_next(session: Session, worker_id: str, *, lease_seconds: int = DEFAULT_LEASE_SECONDS) -> UUID | None:
    """Legacy borrowed-session entry; the compatibility boundary assembles persistence."""
    from .compatibility import claim_next as claim
    return claim(session, worker_id, lease_seconds=lease_seconds)


def process_claimed(session: Session, task_id: UUID, worker_id: str) -> bool:
    """Retain P1 delivery handling; the worker's Native path uses ExecutionPreparer instead."""
    from .compatibility import process_claimed as process
    return process(session, task_id, worker_id)


class RunLeaseService:
    """Claim deliveries and preserve the original P1 cancellation/failure/recovery behavior."""
    def __init__(self, unit_of_work: RunCommandUnitOfWork):
        self.unit_of_work = unit_of_work

    def claim(self, worker_id: str, *, lease_seconds: int = DEFAULT_LEASE_SECONDS) -> UUID | None:
        """Claim the oldest available delivery under one queue transaction."""
        now = utc_now()
        with self.unit_of_work as work:
            return work.outbox.claim(worker_id, now, now + timedelta(seconds=lease_seconds))

    def process(self, task_id: UUID, worker_id: str) -> bool:
        """Process only a matching pending lease; uncertain prior execution is interrupted.

        Return False for missing/completed/foreign leases. This compatibility path has no
        Runtime and persists started/failed on first execution; it never executes a tool.
        Delivery completion, state, ordered events and audit are one atomic transaction.
        """
        now = utc_now()
        with self.unit_of_work as work:
            task = work.outbox.lock_delivery(task_id)
            if task is None or task.completed_at is not None or task.lease_owner != worker_id:
                return False
            run = work.runs.for_delivery(task)
            if run is None or RunStatus(run.status).terminal:
                work.outbox.complete_delivery(task.id, now, clear_lease=False)
                return True
            if task.message_type == 'run.cancel' or run.cancel_requested_at is not None:
                transition_run(run, RunStatus.CANCELLED)
                run.ended_at = now
                work.runs.save(run)
                work.events.append(run.id, 'run.cancelled', {'status': run.status}, now)
                work.audit.write(run.tenant_id, run.principal_id, 'run.cancelled', 'run', str(run.id))
            elif task.message_type == 'run.execute':
                if run.status == RunStatus.RUNNING.value or run.attempt > 0:
                    transition_run(run, RunStatus.INTERRUPTED)
                    run.error_code = 'worker_lease_expired'
                    run.error_message = 'Worker lost the lease before the run reached a known outcome'
                    run.ended_at = now
                    work.runs.save(run)
                    work.events.append(run.id, 'run.interrupted', {
                        'status': run.status, 'error_code': run.error_code,
                    }, now)
                    work.audit.write(run.tenant_id, run.principal_id, 'run.interrupted', 'run', str(run.id),
                                     {'error_code': run.error_code})
                else:
                    transition_run(run, RunStatus.RUNNING)
                    run.attempt += 1
                    run.started_at = now
                    work.runs.save(run)
                    work.events.append(run.id, 'run.started', {'status': run.status}, now)
                    transition_run(run, RunStatus.FAILED)
                    run.error_code = 'runtime_not_configured'
                    run.error_message = 'P1 persists runs; no runtime executor is configured yet'
                    run.ended_at = now
                    work.runs.save(run)
                    work.events.append(run.id, 'run.failed', {
                        'status': run.status, 'error_code': run.error_code,
                    }, now)
                    work.audit.write(run.tenant_id, run.principal_id, 'run.failed', 'run', str(run.id),
                                     {'error_code': run.error_code})
            work.outbox.complete_delivery(task.id, now, clear_lease=True)
        return True
