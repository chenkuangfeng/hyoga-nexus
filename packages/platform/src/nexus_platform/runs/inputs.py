"""Input response policy and atomic resume orchestration, with no ORM dependencies."""
from uuid import UUID
from nexus_core.platform import Principal, utc_now
from nexus_platform.errors import Conflict, NotFound
from .command_ports import RunCommandUnitOfWork
from .domain import Run


class RunInputService:
    """Consume a user's response exactly once and reactivate its execution delivery."""
    def __init__(self, unit_of_work: RunCommandUnitOfWork):
        self.unit_of_work = unit_of_work

    def respond(self, principal: Principal, tenant_id: UUID, run_id: UUID,
                input_request_id: UUID, response: str, key: str) -> Run:
        """Reauthorize and lock the Run before checking input ownership and idempotency.

        The actual key is not trimmed. A consumed identical answer can replay even after
        the Run has advanced; differing answers conflict. No event, answer or queue update
        survives a failed transaction. Invisible Run/input raises NotFound.
        """
        if not key.strip() or len(key) > 255:
            raise ValueError('Idempotency-Key must contain 1 to 255 characters')
        with self.unit_of_work as work:
            user_id = work.access.require_principal(principal, tenant_id)
            run = work.runs.owned_for_update(tenant_id, user_id, run_id)
            if run is None:
                raise NotFound('Run not found')
            request = work.inputs.get(input_request_id)
            if request is None or request.run_id != run.id:
                raise NotFound('Input request not found')
            if request.responded_at:
                if request.response_key != key or request.response != response:
                    raise Conflict('Input request already consumed')
                return run
            if run.status != 'waiting_input' or run.cancel_requested_at:
                raise Conflict('Run is not waiting for input')
            work.inputs.consume(request.id, response, key, utc_now())
            work.messages.user_input(run, response)
            work.events.append(run.id, 'input.received', {'input_request_id': str(request.id)}, utc_now())
            work.outbox.requeue_execute(run.id, utc_now())
            work.audit.write(tenant_id, user_id, 'input.received', 'run', str(run.id))
            return run


from .compatibility import respond_input
