"""Resume a suspended tool batch without repeating any already completed invocation."""
from dataclasses import asdict
import json
from nexus_core.runtime import ModelMessage, RuntimeFault, RuntimeOutcome, ToolCall, ToolDisposition
from .tools import execute_batch


async def resume_tools(state, gateway, token, definitions, hook, turn, append, *, progress, budget, working):
    """Consume original call IDs after action approval; keep pending calls on another suspension."""
    pending = [ToolCall(**value) for value in state.get('pending_calls', [])]
    if not pending:
        return None
    async for index, result in execute_batch(pending, definitions, gateway, token, hook, turn):
        if result.disposition == ToolDisposition.WAIT_APPROVAL:
            state['pending_calls'] = [asdict(call) for call in pending[index:]]
            return RuntimeOutcome('waiting_approval')
        await append(ModelMessage('tool', result.data, tool_call_id=pending[index].id))
        state['pending_calls'] = [asdict(call) for call in pending[index + 1:]]
        progress.errors += bool(result.error_code)
        if pending[index].name == 'update_working_checkpoint' and not result.error_code:
            arguments = json.loads(pending[index].arguments)
            working.key_info = str(arguments.get('key_info', arguments.get('content', '')))
            state['key_info'] = working.key_info
        if result.disposition != ToolDisposition.CONTINUE:
            for call in pending[index + 1:]:
                await append(ModelMessage('tool', 'Not executed: previous tool ended this turn.', tool_call_id=call.id))
            state['pending_calls'] = []
            if result.disposition == ToolDisposition.WAIT_INPUT:
                return RuntimeOutcome('waiting_input', question=result.data, candidates=result.candidates)
            return RuntimeOutcome(result.exit_status or ('failed' if result.error_code else 'completed'), result.error_code)
        if result.continuation:
            await append(ModelMessage('user', result.continuation))
        if progress.errors >= budget.max_errors:
            raise RuntimeFault('budget_exhausted')
    return None
