"""delegate_task and the sub-agent runner (openspec 2026-11-07-tool-expansion, section 8.1)."""
import asyncio
import json
from uuid import uuid4

import pytest

from nexus_core.native import NativePolicy
from nexus_core.runtime import ExecutionBudget, ModelChunk, RuntimeProgress, ToolCall, ToolDefinition, ToolResult
from nexus_runtimes.native.engine.cancellation import CancellationToken
from nexus_tools.builtins import builtins
from nexus_tools.builtins.collab import collab_tools
from nexus_tools.builtins.services import RunServices
from nexus_tools.gateway import AuthorizedToolGateway
from nexus_tools.registry import RegisteredTool, ToolRegistry
from nexus_worker.subagent import EXCLUDED_TOOLS, SubagentRunner


class Model:
    """Scripted model: each entry is a list of chunks for one turn."""

    def __init__(self, turns):
        self.turns, self.requests, self.closed = iter(turns), [], False

    async def stream(self, request):
        self.requests.append(request)
        chunks = next(self.turns)
        for chunk in chunks:
            yield chunk
        yield ModelChunk('done', finish_reason='tool_calls' if any(c.kind == 'tool_call' for c in chunks) else 'stop')

    async def close(self):
        self.closed = True


def text(value):
    return ModelChunk('text', text=value)


def tool_call(name, **arguments):
    return ModelChunk('tool_call', tool_call=ToolCall(str(uuid4()), name, json.dumps(arguments)))


class Access:
    def __init__(self):
        self.started, self.approvals = [], []

    async def authorize(self, name, version):
        return 'b'

    async def start(self, call, binding_id):
        self.started.append(call.name)
        return str(uuid4())

    async def finish(self, *a):
        return None

    async def denied(self, name):
        return None

    async def approval(self, call, **kw):
        self.approvals.append(call.name)
        return call.arguments

    async def grant(self, call):
        return False


class Store:
    def __init__(self):
        self.events = []

    async def emit(self, kind, payload):
        self.events.append((kind, payload))


def registry():
    tools = ToolRegistry()
    schema = {'type': 'object', 'properties': {'q': {'type': 'string'}}, 'additionalProperties': False}
    for name, kwargs in (('lookup', dict(read_only=True, idempotent=True, risk='read')),
                         ('send_mail', dict(side_effects=True, risk='write', requires_approval=True)),
                         ('ask_user', dict(read_only=True, idempotent=True, risk='read')),
                         ('delegate_task', dict(side_effects=True, risk='write'))):
        tools.register(RegisteredTool(ToolDefinition(name, name, schema, **kwargs),
                                      lambda args, ctx, name=name: ToolResult(f'{name} done'), lambda r: r.data))
    return tools


def runner(model, *, bindings=None, hidden=frozenset(), policy=None, progress=None, budget=None, token=None):
    store, access = Store(), Access()
    parent_bindings = bindings or {'lookup': 'v1', 'send_mail': 'v1', 'ask_user': 'v1', 'delegate_task': 'v1'}
    return SubagentRunner(
        build_model=lambda: model, registry=registry(), parent_bindings=parent_bindings,
        parent_policy=policy or NativePolicy(), hidden_groups=hidden, access=access, services_store=object(), sandbox=None,
        token=token or CancellationToken(), parent_progress=progress or RuntimeProgress(),
        parent_budget=budget or ExecutionBudget(max_tokens=30000), emit=store.emit, run_id='r1', session_id='s1', tenant_id='t1'), store, access


def run(coro):
    return asyncio.run(coro)


def test_the_sub_agent_answers_with_a_subset_of_the_parents_tools():
    model = Model([[tool_call('lookup', q='x')], [text('The answer is 42.')]])
    sub, store, access = runner(model)
    answer, error = run(sub.run('Find the answer', 'some context'))
    assert (answer, error) == ('The answer is 42.', None)
    offered = {t.name for t in model.requests[0].tools}
    assert offered == {'lookup', 'send_mail'} and not offered & EXCLUDED_TOOLS
    prompt = ' '.join(m.content for m in model.requests[0].messages)
    assert 'Find the answer' in prompt and 'some context' in prompt and 'sub-agent' in prompt
    assert access.started == ['lookup'] and model.closed
    assert [kind for kind, _ in store.events] == ['subagent.started', 'subagent.finished']
    assert store.events[1][1]['status'] == 'completed'


def test_requested_tools_can_only_narrow_never_widen():
    sub, _, _ = runner(Model([]), bindings={'lookup': 'v1', 'ask_user': 'v1'})
    assert sub.tools_for(None) == {'lookup': 'v1'}
    assert sub.tools_for(['lookup', 'send_mail', 'ask_user', 'delegate_task', 'nonsense']) == {'lookup': 'v1'}
    assert sub.tools_for([]) == {}


def test_actions_needing_approval_are_refused_inside_the_sub_agent():
    model = Model([[tool_call('send_mail', q='hi')], [text('Could not send.')]])
    sub, _, access = runner(model)
    answer, error = run(sub.run('Send a mail'))
    assert error is None and access.approvals == []  # nobody to ask: the parent decides
    tool_message = next(m for m in model.requests[1].messages if m.role == 'tool')
    assert 'approval' in tool_message.content.lower()


def test_tokens_are_charged_to_the_parent_and_the_budget_is_a_share_of_it():
    progress = RuntimeProgress()
    sub, _, _ = runner(Model([[text('done')]]), progress=progress, budget=ExecutionBudget(max_tokens=30000, max_rounds=12))
    budget = sub.budget_for(99)
    assert budget.max_rounds == 12 and budget.max_tokens == 10000 and budget.max_seconds == 60
    run(sub.run('task'))
    assert progress.tokens > 0
    progress.tokens = 29500
    with pytest.raises(Exception) as error:
        sub.budget_for(None)
    assert getattr(error.value, 'code', '') == 'budget_exhausted'


def test_a_failed_sub_run_reports_the_code_and_still_closes_the_model():
    class Broken(Model):
        async def stream(self, request):
            raise RuntimeError('provider down')
            yield  # pragma: no cover
    model = Broken([])
    sub, store, _ = runner(model)
    answer, error = run(sub.run('task'))
    assert error and not answer and model.closed
    assert store.events[-1][0] == 'subagent.finished' and store.events[-1][1]['status'] != 'completed'


def test_the_delegate_tool_returns_the_answer_or_a_failure_result():
    tool = next(collab_tools())

    class Fake:
        def __init__(self, result):
            self.result, self.seen = result, []

        async def run(self, task, context, tools, max_rounds):
            self.seen.append((task, context, tools, max_rounds))
            return self.result

    def call(delegate, **arguments):
        return run(tool.handler(arguments, type('C', (), {'services': RunServices(object(), {}, None, delegate)})()))
    ok = Fake(('result text', None))
    assert call(ok, task='t', context='c', tools=['lookup'], max_rounds=3).data == 'result text'
    assert ok.seen == [('t', 'c', ['lookup'], 3)]
    failed = call(Fake(('partial', 'budget_exhausted')), task='t')
    assert failed.error_code == 'budget_exhausted' and 'partial' in failed.data
    assert call(None, task='t').error_code == 'delegate_unavailable'


def test_delegate_task_is_a_collab_group_write_tool_and_hidden_by_default():
    definition = builtins().get('delegate_task', 'v1').definition
    assert (definition.group, definition.risk, definition.side_effects) == ('collab', 'write', True)
    from nexus_core.native import group_enabled
    assert group_enabled({}, 'collab') is False


def test_the_gateway_of_a_sub_agent_cannot_reach_the_collab_group():
    sub, _, _ = runner(Model([[text('ok')]]), hidden=frozenset({'sandbox'}))
    assert sub.hidden_groups == frozenset({'sandbox'})  # 'collab' is added when the gateway is built
    model = Model([[text('ok')]])
    sub, _, _ = runner(model, bindings={'lookup': 'v1', 'delegate_task': 'v1'})
    run(sub.run('task'))
    assert 'delegate_task' not in {t.name for t in model.requests[0].tools}
