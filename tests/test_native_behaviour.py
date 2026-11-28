"""Behaviour added by OpenSpec native-engine-behaviour: continuation, final-turn tools, todo, attempts (3.7, 3.10, 3.15).

Integration cases reuse the database harness from test_native_runtime; unit cases pin the components.
"""
from __future__ import annotations

import asyncio
import pytest
from sqlalchemy import select

from test_native_runtime import FakeModel, call, registry, run_row, stack
from test_platform import database  # noqa: F401  (pytest fixture)
from nexus_core.native import NativePolicy
from nexus_core.runtime import ExecutionBudget, ModelChunk, RuntimeFault, RuntimeProgress, ToolDefinition, ToolResult
from nexus_platform.persistence.models import NativeRunStateRecord, ToolInvocationRecord
from nexus_runtimes.native.engine.orchestrator import AttemptCounter
from nexus_runtimes.native.models.retry import RetryModel
from nexus_tools.builtins.services import RunServices
from nexus_tools.builtins.todo import todo_tool
from nexus_tools.registry import RegisteredTool
from nexus_worker.__main__ import run_once


def _run_with(database, model, *, budgets=None, names=('echo',)):
    principal, tenant, _, run, _ = stack(database, list(names), budgets=budgets)
    async def echo(args, context):
        return ToolResult(args['text'])
    run_once(database, 'worker', model_factory=lambda _: model, registry_factory=lambda _: registry(echo))
    return run_row(database, run.id), run


def _event_kinds(database, run):
    from nexus_platform.runs.service import list_events
    from nexus_platform.persistence.models import RunRecord
    with database() as db:
        row = db.get(RunRecord, run.id)
        tenant_id = row.tenant_id
    principal_events = []
    with database() as db:
        from nexus_core.platform import Principal
        principal = Principal('native-owner', 'test')
        principal_events = [event.event_type for event in list_events(db, principal, tenant_id, run.id, 0)]
    return principal_events


# ---------- 3.7 continuation and final turn (integration) ----------

def test_truncated_final_answer_is_continued_and_the_run_completes(database):
    async def truncated():
        yield ModelChunk('text', text='The first part')
        yield ModelChunk('done', finish_reason='length')
    model = FakeModel([truncated, [ModelChunk('text', text=' and the rest')]])
    run, row = _run_with(database, model)
    assert run.status == 'completed'
    assert len(model.requests) == 2
    assert any(m.role == 'user' and 'cut off' in m.content for m in model.requests[1].messages)
    assert 'answer.continued' in _event_kinds(database, row)


def test_last_allowed_turn_withdraws_tools_and_says_so(database):
    model = FakeModel([[call('echo', '{"text":"a"}')], [ModelChunk('text', text='Final')]])
    run, _ = _run_with(database, model, budgets={'max_rounds': 2, 'max_tokens': 100000})
    assert run.status == 'completed'
    assert model.requests[0].tools  # tools are offered before the final turn
    assert model.requests[1].tools == ()
    assert any('last allowed turn' in m.content for m in model.requests[1].messages)


def test_tool_call_on_the_final_turn_is_refused_and_not_executed(database):
    model = FakeModel([[call('echo', '{"text":"a"}')], [call('echo', '{"text":"b"}')]])
    run, _ = _run_with(database, model, budgets={'max_rounds': 2, 'max_tokens': 100000})
    assert run.status == 'failed'
    with database() as db:
        invocations = list(db.scalars(select(ToolInvocationRecord).where(ToolInvocationRecord.run_id == run.id)))
    # Only the first-turn call ran; the final-turn call was refused without invoking the tool.
    assert len(invocations) == 1


# ---------- 3.15 model attempts (unit) ----------

class _Counter:
    def __init__(self):
        self.count = 0
    async def begin_attempt(self):
        self.count += 1


class _Flaky:
    """Fails with a retryable fault before output, then streams one answer."""
    def __init__(self, failures):
        self.failures = failures
        self.calls = 0
    async def stream(self, request):
        self.calls += 1
        if self.calls <= self.failures:
            raise RuntimeFault('model_provider_unavailable')
        yield ModelChunk('text', text='ok')
        yield ModelChunk('done', finish_reason='stop')
    async def close(self):
        return None


def _retry(failures, counter):
    policy = NativePolicy(model_retries=2, retry_delay_seconds=0, max_retry_delay_seconds=0)
    model = RetryModel(_Flaky(failures), policy)
    model.bind_attempts(counter)
    return model


async def _drain(stream):
    return [chunk async for chunk in stream]


def test_every_real_request_including_retries_is_counted():
    counter = _Counter()
    model = _retry(failures=2, counter=counter)
    chunks = asyncio.run(_drain(model.stream(None)))
    assert counter.count == 3
    assert chunks[0].text == 'ok'


def test_attempt_counter_refuses_requests_beyond_the_cap_before_sending():
    progress = RuntimeProgress(model_attempts=2)
    class _Store:
        async def emit(self, kind, payload):
            return None
    counter = AttemptCounter(progress, _Store(), limit=2)
    with pytest.raises(RuntimeFault, match='budget_exhausted'):
        asyncio.run(counter.begin_attempt())
    assert progress.model_attempts == 2


def test_attempt_counter_persists_on_progress_and_older_rows_read_as_zero():
    assert RuntimeProgress().model_attempts == 0
    assert RuntimeProgress(**{'turns': 1, 'tokens': 0, 'errors': 0, 'active_seconds': 0, 'state': {}}).model_attempts == 0


def test_attempt_cap_is_derived_when_not_set_and_rejects_negative_values():
    assert ExecutionBudget().max_model_attempts == 0
    assert ExecutionBudget().max_tokens == 0
    with pytest.raises(ValueError):
        ExecutionBudget(max_model_attempts=-1)
    with pytest.raises(ValueError):
        ExecutionBudget(max_tokens=-1)


# ---------- 3.10 todo (unit) ----------

class _Ctx:
    def __init__(self, state):
        self.services = RunServices(store=object(), run_state=state)


def _todo(arguments, state):
    definition = todo_tool()
    return asyncio.run(definition.handler(arguments, _Ctx(state)))


def test_todo_set_then_list_reads_back_from_run_state():
    state = {}
    set_result = _todo({'op': 'set', 'items': [{'text': 'Read spec', 'status': 'done'},
                                                {'text': 'Write tests', 'status': 'in_progress'}]}, state)
    assert '[x] Read spec' in set_result.data and '[~] Write tests' in set_result.data
    listed = _todo({'op': 'list'}, state)
    assert listed.data == set_result.data


def test_todo_list_on_an_empty_run_says_so_and_set_without_items_is_refused():
    state = {}
    assert _todo({'op': 'list'}, state).data == 'No todos.'
    refused = _todo({'op': 'set'}, state)
    assert refused.error_code == 'tool_arguments_invalid'


def test_todo_refuses_to_run_without_run_scoped_state():
    class _Bare:
        services = None
    with pytest.raises(RuntimeFault, match='tool_unavailable'):
        asyncio.run(todo_tool().handler({'op': 'list'}, _Bare()))
