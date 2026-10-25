"""Run cancellation state policy; persistence and ownership queries are transaction ports."""
from uuid import UUID
from nexus_core.platform import Principal, RunStatus, utc_now
from nexus_platform.errors import NotFound
from .command_ports import RunCommandUnitOfWork
from .domain import Run
from .state import transition_run


class RunCancellationService:
    """Stop idle Runs immediately; signal active execution without claiming it has stopped."""
    def __init__(self, unit_of_work: RunCommandUnitOfWork):
        self.unit_of_work = unit_of_work

    def cancel(self, principal: Principal, workspace_id: UUID, run_id: UUID) -> Run:
        """Cancel under the owner lock, raising NotFound for invisible Runs.

        A terminal Run is unchanged. Waiting/queued Runs complete pending deliveries and
        emit cancelled before cancel_requested. Active Runs retain their execution status
        until the worker stops; one pending cancellation delivery is ensured.
        """
        now = utc_now()
        with self.unit_of_work as work:
            user_id = work.access.require_principal(principal, workspace_id)
            run = work.runs.owned_for_update(workspace_id, user_id, run_id)
            if run is None:
                raise NotFound("Run not found")
            if RunStatus(run.status).terminal:
                return run
            if run.status in (RunStatus.QUEUED.value, RunStatus.WAITING_INPUT.value,
                              RunStatus.WAITING_APPROVAL.value):
                transition_run(run, RunStatus.CANCELLED)
                run.cancel_requested_at = now
                run.ended_at = now
                work.runs.save(run)
                work.outbox.complete_pending(run.id, now)
                work.events.append(run.id, "run.cancelled", {"status": run.status}, now)
            else:
                run.cancel_requested_at = now
                work.runs.save(run)
                if not work.outbox.has_pending(run.id, 'run.cancel'):
                    work.outbox.enqueue(run.id, 'run.cancel', now)
            work.events.append(run.id, "run.cancel_requested", {"status": run.status}, now)
            work.audit.write(workspace_id, user_id, "run.cancel_requested", "run", str(run.id))
        return run


from .compatibility import request_cancel
