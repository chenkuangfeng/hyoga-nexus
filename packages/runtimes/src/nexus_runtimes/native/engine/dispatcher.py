"""Tool dispatch for one model turn (OpenSpec native-engine-split, 3.8).

The dispatcher owns the per-result policy of a normal turn: approval suspension, error accounting,
working-checkpoint capture, terminal dispositions and continuations. Ordering and read/mutation
barriers stay in `execute_batch`. The resume path (`recovery.resume_tools`) keeps its own mapping on
purpose: its outcome rules differ, and merging them would change observable behaviour.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

from nexus_core.runtime import ModelMessage, RuntimeFault, RuntimeOutcome, ToolDisposition

from .tools import execute_batch


@dataclass
class DispatchResult:
    """What the turn needs from a batch: whether the Run ended, and any prompts to add otherwise."""
    terminal: bool = False
    outcome: RuntimeOutcome | None = None
    continuations: list[str] = field(default_factory=list)


class ToolDispatcher:
    """Execute one turn's tool calls in model order and project each result into the transcript."""

    def __init__(self, gateway, *, parallel: bool):
        self.gateway = gateway
        self.parallel = parallel

    async def dispatch(self, calls, definitions, token, hook, turn, *, append, state, progress, budget, working) -> DispatchResult:
        """Run the batch; stop at the first terminal disposition and mark the remaining calls as not executed.

        Raises RuntimeFault for an invalid exit status or when the error budget is exhausted, as the engine did before.
        """
        continuations: list[str] = []
        async for index, result in execute_batch(calls, definitions, self.gateway, token, hook, turn, self.parallel):
            call = calls[index]
            if result.disposition == ToolDisposition.WAIT_APPROVAL:
                state['pending_calls'] = [asdict(pending) for pending in calls[index:]]
                return DispatchResult(terminal=True, outcome=RuntimeOutcome('waiting_approval'))
            progress.errors += bool(result.error_code)
            await append(ModelMessage('tool', result.data, tool_call_id=call.id))
            if call.name == 'update_working_checkpoint' and not result.error_code:
                arguments = json.loads(call.arguments)
                working.key_info = str(arguments.get('key_info', arguments.get('content', '')))
                state['key_info'] = working.key_info
            if result.disposition != ToolDisposition.CONTINUE:
                for deferred in calls[index + 1:]:
                    await append(ModelMessage('tool', 'Not executed: previous tool ended this turn.', tool_call_id=deferred.id))
                if result.disposition == ToolDisposition.WAIT_INPUT:
                    outcome = RuntimeOutcome('waiting_input', question=result.data, candidates=result.candidates)
                elif result.disposition == ToolDisposition.COMPLETE:
                    outcome = RuntimeOutcome('failed' if result.error_code else 'completed', result.error_code)
                elif result.exit_status in ('completed', 'failed'):
                    outcome = RuntimeOutcome(result.exit_status, result.error_code)
                else:
                    # Kept from the earlier engine. Unreachable with the current ToolDisposition values
                    # (COMPLETE and WAIT_INPUT are handled above); retained so the guard survives new dispositions.
                    raise RuntimeFault('tool_exit_invalid')
                return DispatchResult(terminal=True, outcome=outcome)
            if result.continuation:
                continuations.append(result.continuation)
            if progress.errors >= budget.max_errors:
                raise RuntimeFault('budget_exhausted')
        return DispatchResult(terminal=False, continuations=continuations)
