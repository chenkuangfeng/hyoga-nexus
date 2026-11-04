"""Unit tests for the components split out of the Native engine (OpenSpec native-engine-split, 6.x).

Integration behaviour (persistence, cancellation, budgets, resume) stays in the test_native_* suites
and the golden baseline. These tests pin each component's contract on its own.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import pytest

from nexus_core.native import NativePolicy
from nexus_core.runtime import (
    AgentRuntime, ExecutionBudget, ModelMessage, RunContext, RunRequest, RuntimeCapabilities,
    RuntimeFault, RuntimeProgress, ToolCall, ToolDefinition, ToolDisposition, ToolResult,
)
from nexus_runtimes.native.context.assembler import ContextAssembler, message_bytes
from nexus_runtimes.native.context.working import WorkingMemory
from nexus_runtimes.native.engine.cancellation import CancellationToken
from nexus_runtimes.native.engine.completion import CompletionJudge, JudgeDecision
from nexus_runtimes.native.engine.dispatcher import ToolDispatcher
from nexus_runtimes.native.engine.orchestrator import RunOrchestrator


# ---------- 3.3 contract and 3.9 tool definition fields ----------

def test_runtime_capabilities_default_to_full_native_support():
    assert RuntimeCapabilities() == RuntimeCapabilities(True, True, True, True, True)


def test_native_orchestrator_implements_the_runtime_port():
    orchestrator = RunOrchestrator(model=None, tools=None, store=None)
    assert orchestrator.capabilities() == RuntimeCapabilities()
    assert callable(orchestrator.run)
    port: AgentRuntime = orchestrator  # structural check; mypy-style assignment documents the contract
    assert port is orchestrator


def test_run_request_and_context_are_frozen_inputs():
    request = RunRequest('run-1', (ModelMessage('user', 'hi'),), ExecutionBudget())
    with pytest.raises(AttributeError):
        request.run_id = 'other'  # type: ignore[misc]
    context = RunContext(CancellationToken())
    assert context.progress is None


def test_tool_definition_risk_and_capabilities_have_safe_defaults():
    definition = ToolDefinition('lookup', 'Read a value', {'type': 'object'})
    assert definition.risk_level == 'medium'
    assert definition.required_capabilities == ()


@pytest.mark.parametrize('level', ['low', 'medium', 'high'])
def test_tool_definition_accepts_the_three_risk_levels(level):
    assert ToolDefinition('t', 'd', {}, risk_level=level).risk_level == level


def test_tool_definition_rejects_unknown_risk_level():
    with pytest.raises(ValueError, match='unknown risk level'):
        ToolDefinition('t', 'd', {}, risk_level='critical')  # type: ignore[arg-type]


# ---------- 3.7 completion judge ----------

def _judge(**policy):
    state: dict[str, object] = {}
    return CompletionJudge(NativePolicy(**policy), state), state


def test_tool_calls_are_executed_when_not_truncated():
    judge, _ = _judge()
    decision = judge.judge('', 'tool_calls', (ToolCall('c1', 'echo', '{}'),))
    assert decision.decision == JudgeDecision.EXECUTE_TOOLS


def test_truncated_tool_call_is_never_executed_and_stalls_after_the_limit():
    judge, state = _judge(repeated_limit=2)
    call = (ToolCall('c1', 'echo', '{"text":"cut'),)
    first = judge.judge('', 'length', call)
    assert first.decision == JudgeDecision.INCOMPLETE_TOOL_CALL and first.error_code is None
    second = judge.judge('', 'length', call)
    assert second.decision == JudgeDecision.INCOMPLETE_TOOL_CALL and second.error_code == 'model_stuck'
    assert state['truncated_calls'] == 2


def test_empty_response_is_retried_with_a_visible_prompt_then_fails_when_exhausted():
    judge, _ = _judge(empty_retries=0)
    decision = judge.judge('', 'stop', ())
    assert decision.decision == JudgeDecision.FAIL
    assert decision.error_code == 'model_response_unusable'
    judge, _ = _judge(empty_retries=1)
    retry = judge.judge('', 'stop', ())
    assert retry.decision == JudgeDecision.RETRY_EMPTY
    assert retry.prompt.startswith('[ERROR] Blank response')


def test_natural_answer_is_accepted_and_truncated_text_is_marked():
    judge, _ = _judge()
    assert judge.judge('Done.', 'stop', ()).decision == JudgeDecision.ACCEPT
    assert judge.judge('Partial answer', 'length', ()).decision == JudgeDecision.ACCEPT_TRUNCATED


def test_content_filter_fails_with_a_stable_code():
    judge, _ = _judge()
    decision = judge.judge('x', 'content_filter', ())
    assert decision.decision == JudgeDecision.FAIL
    assert decision.error_code == 'model_content_filtered'


def test_repeated_identical_answers_are_reported_as_stalled():
    judge, _ = _judge(repeated_limit=2)
    assert judge.judge('Same', 'stop', ()).decision == JudgeDecision.ACCEPT
    stalled = judge.judge('Same', 'stop', ())
    assert stalled.decision == JudgeDecision.STALLED
    assert stalled.error_code == 'model_stuck'


# ---------- 3.8 tool dispatcher ----------

@dataclass
class _Gateway:
    results: dict
    seen: list = field(default_factory=list)

    async def execute(self, call, token):
        self.seen.append(call.name)
        return self.results[call.id]


@dataclass
class _Working:
    key_info: str = ''


def _defs(*names):
    return tuple(ToolDefinition(name, name, {}) for name in names)


async def _noop_hook(phase, turn, name):
    return None


def _dispatch(calls, results, *, definitions=None, max_errors=4, parallel=False):
    gateway = _Gateway(results)
    dispatcher = ToolDispatcher(gateway, parallel=parallel)
    messages: list[ModelMessage] = []
    state: dict[str, object] = {}
    progress = RuntimeProgress()
    async def append(message):
        messages.append(message)
    result = asyncio.run(dispatcher.dispatch(
        calls, definitions or _defs(*{c.name for c in calls}), CancellationToken(), _noop_hook, 1,
        append=append, state=state, progress=progress,
        budget=ExecutionBudget(max_errors=max_errors), working=_Working()))
    return result, messages, state, progress, gateway


def test_results_are_projected_in_model_order_and_continuations_are_collected():
    calls = (ToolCall('a', 'echo', '{}'), ToolCall('b', 'echo', '{}'))
    results = {'a': ToolResult('first', continuation='note A'), 'b': ToolResult('second')}
    result, messages, _, _, gateway = _dispatch(calls, results)
    assert result.terminal is False
    assert result.continuations == ['note A']
    assert [m.tool_call_id for m in messages] == ['a', 'b']
    assert gateway.seen == ['echo', 'echo']


def test_approval_suspends_the_turn_and_keeps_the_remaining_calls():
    calls = (ToolCall('a', 'write', '{}'), ToolCall('b', 'write', '{}'))
    results = {'a': ToolResult('', disposition=ToolDisposition.WAIT_APPROVAL), 'b': ToolResult('never')}
    result, messages, state, _, _ = _dispatch(calls, results)
    assert result.terminal and result.outcome.status == 'waiting_approval'
    assert [item['id'] for item in state['pending_calls']] == ['a', 'b']
    assert messages == []


def test_wait_input_is_terminal_and_marks_later_calls_as_not_executed():
    calls = (ToolCall('a', 'ask_user', '{}'), ToolCall('b', 'echo', '{}'))
    results = {'a': ToolResult('Which?', disposition=ToolDisposition.WAIT_INPUT, candidates=('x', 'y')),
               'b': ToolResult('never')}
    result, messages, _, _, gateway = _dispatch(calls, results)
    assert result.terminal and result.outcome.status == 'waiting_input'
    assert result.outcome.candidates == ('x', 'y')
    assert messages[-1].content == 'Not executed: previous tool ended this turn.'
    assert gateway.seen == ['ask_user']


def test_complete_disposition_maps_by_error_code_regardless_of_exit_status():
    # COMPLETE is handled before exit_status is consulted, so the exit status cannot override it.
    calls = (ToolCall('a', 'finish', '{}'),)
    ok = _dispatch(calls, {'a': ToolResult('done', disposition=ToolDisposition.COMPLETE, exit_status='unknown')})[0]
    assert ok.outcome.status == 'completed'
    failed = _dispatch(calls, {'a': ToolResult('bad', disposition=ToolDisposition.COMPLETE, error_code='x')})[0]
    assert failed.outcome.status == 'failed'


def test_error_budget_exhaustion_stops_the_run_explicitly():
    calls = (ToolCall('a', 'echo', '{}'), ToolCall('b', 'echo', '{}'))
    results = {'a': ToolResult('bad', error_code='tool_failed'), 'b': ToolResult('ok')}
    with pytest.raises(RuntimeFault, match='budget_exhausted'):
        _dispatch(calls, results, max_errors=1)


# ---------- 3.6 context assembler ----------

class _Store:
    def __init__(self):
        self.events = []

    async def emit(self, kind, payload):
        self.events.append((kind, payload))


def _assembler():
    return ContextAssembler(model=None, store=_Store(), policy=NativePolicy())


def test_definitions_are_frozen_and_a_changed_schema_fails_explicitly():
    assembler = _assembler()
    definitions = _defs('echo')
    with pytest.raises(RuntimeFault, match='context_prefix_changed'):
        assembler.ensure_frozen(definitions)  # not frozen yet
    assembler.freeze(definitions)
    assembler.ensure_frozen(_defs('echo'))  # equal schema is accepted
    with pytest.raises(RuntimeFault, match='context_prefix_changed'):
        assembler.ensure_frozen(_defs('echo', 'write'))


def test_view_counts_message_bytes_and_definition_size_for_the_budget():
    assembler = _assembler()
    definitions = _defs('echo')
    assembler.freeze(definitions)
    history = [ModelMessage('user', 'hello')]
    working = WorkingMemory({}, NativePolicy())
    view = assembler.view(history, working=working, turn=1)
    assert view.input_estimate >= message_bytes(view.messages) + len(str(definitions).encode())


def test_message_bytes_counts_content_and_tool_arguments():
    message = ModelMessage('assistant', 'abc', (ToolCall('c', 'echo', '{"x":1}'),))
    assert message_bytes([message]) == len('abc') + len('{"x":1}') + len('echo')
