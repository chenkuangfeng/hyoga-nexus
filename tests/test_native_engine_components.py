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
    AgentRuntime, ExecutionBudget, ModelChunk, ModelMessage, RunContext, RunRequest, RuntimeCapabilities,
    RuntimeFault, RuntimeProgress, ToolCall, ToolDefinition, ToolDisposition, ToolResult,
)
from nexus_runtimes.native.context.assembler import ContextAssembler, estimate_message_tokens, message_bytes
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
    assert request.budget.max_tokens == 0
    with pytest.raises(AttributeError):
        request.run_id = 'other'  # type: ignore[misc]
    context = RunContext(CancellationToken())
    assert context.progress is None


def test_tool_definition_risk_and_capabilities_have_safe_defaults():
    definition = ToolDefinition('lookup', 'Read a value', {'type': 'object'})
    assert definition.risk_level == 'medium' and definition.risk == 'write'
    assert definition.required_capabilities == ()


@pytest.mark.parametrize('risk, level', [('read', 'low'), ('probe', 'low'), ('write', 'medium'), ('destructive', 'high')])
def test_tool_definition_risk_derives_the_legacy_level(risk, level):
    assert ToolDefinition('t', 'd', {}, risk=risk).risk_level == level


def test_tool_definition_rejects_unknown_risk_and_write_risk_on_read_only_tools():
    with pytest.raises(ValueError, match='unknown risk'):
        ToolDefinition('t', 'd', {}, risk='critical')  # type: ignore[arg-type]
    with pytest.raises(ValueError, match='read or probe'):
        ToolDefinition('t', 'd', {}, read_only=True, risk='write')
    assert ToolDefinition('t', 'd', {}, read_only=True).risk == 'read'


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


def test_natural_answer_is_accepted():
    judge, _ = _judge()
    assert judge.judge('Done.', 'stop', ()).decision == JudgeDecision.ACCEPT


def test_truncated_text_is_continued_then_accepted_once_the_bound_is_spent():
    judge, state = _judge(max_continuations=2)
    first = judge.judge('Part one', 'length', ())
    assert first.decision == JudgeDecision.CONTINUE_TRUNCATED and first.prompt
    assert judge.judge('Part two', 'length', ()).decision == JudgeDecision.CONTINUE_TRUNCATED
    assert judge.judge('Part three', 'length', ()).decision == JudgeDecision.ACCEPT_TRUNCATED
    assert state['continuations'] == 2


def test_zero_continuations_keeps_the_previous_accept_truncated_behaviour():
    judge, _ = _judge(max_continuations=0)
    assert judge.judge('Partial answer', 'length', ()).decision == JudgeDecision.ACCEPT_TRUNCATED


def test_a_complete_response_resets_the_continuation_count():
    judge, state = _judge(max_continuations=1)
    assert judge.judge('a', 'length', ()).decision == JudgeDecision.CONTINUE_TRUNCATED
    assert judge.judge('b', 'stop', ()).decision == JudgeDecision.ACCEPT
    assert judge.judge('c', 'length', ()).decision == JudgeDecision.CONTINUE_TRUNCATED


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
        self.messages = []

    async def emit(self, kind, payload):
        self.events.append((kind, payload))

    async def message(self, message):
        self.messages.append(message)

    async def save_progress(self, progress):
        pass


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


def test_view_estimates_tokens_for_messages_and_tool_definitions():
    assembler = _assembler()
    definitions = _defs('echo')
    assembler.freeze(definitions)
    history = [ModelMessage('user', 'hello')]
    working = WorkingMemory({}, NativePolicy())
    view = assembler.view(history, working=working, turn=1)
    assert view.input_estimate >= estimate_message_tokens(view.messages)
    assert view.input_estimate >= (len('hello'.encode()) + 2) // 3


def test_cjk_input_estimate_is_not_charged_as_three_tokens_per_character():
    message = ModelMessage('user', '创建技能' * 100)
    assert message_bytes([message]) == 1200
    assert estimate_message_tokens([message]) < message_bytes([message]) // 2


def test_model_view_compacts_old_exchanges_to_fit_remaining_token_allowance():
    assembler = _assembler()
    definitions = _defs('echo')
    assembler.freeze(definitions)
    call = ToolCall('call-1', 'echo', '{"text":"latest"}')
    messages = [
        ModelMessage('system', 'system instructions'),
        ModelMessage('user', 'old request ' + 'x' * 1500),
        ModelMessage('assistant', 'old response ' + 'y' * 1000),
        ModelMessage('user', 'current skill request'),
        ModelMessage('assistant', '', (call,)),
        ModelMessage('tool', 'latest tool result', tool_call_id=call.id),
    ]
    fitted, estimate, omitted = assembler.fit_token_budget(messages, definitions=definitions, token_budget=500)
    assert omitted == 2
    assert estimate <= 500
    assert 'current skill request' in [message.content for message in fitted]
    assert 'latest tool result' in [message.content for message in fitted]
    assert not any('x' * 100 in message.content for message in fitted)


def test_orchestrator_compacts_history_when_total_token_budget_is_nearly_spent():
    class _Model:
        def __init__(self):
            self.requests = []

        async def stream(self, request):
            self.requests.append(request)
            yield ModelChunk('text', text='完成')
            yield ModelChunk('done', finish_reason='stop')

        async def close(self):
            pass

    class _Tools:
        async def definitions(self):
            return (_defs('echo')[0],)

    old_text = 'historical details ' + 'z' * 7000
    model, store = _Model(), _Store()
    budget = ExecutionBudget(max_tokens=1500, max_output_tokens=256, max_context_chars=20000)
    request = RunRequest('run', (
        ModelMessage('system', 'system'), ModelMessage('user', old_text),
        ModelMessage('assistant', 'older result'), ModelMessage('user', 'create a skill from this'),
    ), budget)
    context = RunContext(CancellationToken(), progress=RuntimeProgress())
    outcome = asyncio.run(RunOrchestrator(model, _Tools(), store).run(request, context))
    assert outcome.status == 'completed'
    sent = model.requests[0].messages
    assert any('Earlier conversation excerpts' in message.content for message in sent)
    assert not any(old_text in message.content for message in sent)
    assert any(message.content == 'create a skill from this' for message in sent)


def test_unlimited_run_continues_past_legacy_cumulative_token_default():
    class _Model:
        def __init__(self):
            self.requests = []
            self.turns = iter((('partial', 'length'), ('完成', 'stop')))

        async def stream(self, request):
            self.requests.append(request)
            text, reason = next(self.turns)
            yield ModelChunk('usage', total_tokens=10000)
            yield ModelChunk('text', text=text)
            yield ModelChunk('done', finish_reason=reason)

        async def close(self):
            pass

    class _Tools:
        async def definitions(self):
            return ()

    model, store = _Model(), _Store()
    progress = RuntimeProgress()
    request = RunRequest('run', (ModelMessage('system', 'system'), ModelMessage('user', 'question')),
                          ExecutionBudget(max_tokens=0, max_rounds=4, max_output_tokens=256))
    outcome = asyncio.run(RunOrchestrator(model, _Tools(), store).run(
        request, RunContext(CancellationToken(), progress=progress)))
    assert outcome.status == 'completed'
    assert len(model.requests) == 2
    assert progress.tokens == 20000


def test_message_bytes_counts_content_and_tool_arguments():
    message = ModelMessage('assistant', 'abc', (ToolCall('c', 'echo', '{"x":1}'),))
    assert message_bytes([message]) == len('abc') + len('{"x":1}') + len('echo')
