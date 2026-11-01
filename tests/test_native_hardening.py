"""Runtime guarantees from the context-performance change: mid-Run revocation (P4), grouped-write
rollback (P7), and read-only parallelism that keeps model order (P9)."""
import asyncio

from nexus_core.runtime import ModelChunk, ToolCall, ToolDefinition, ToolResult
from nexus_core.runtime.budgets import ExecutionBudget
from nexus_platform.authz.resources import revoke_resource_grant
from nexus_platform.persistence.models import MessageRecord, RunEventRecord, RunRecord, ToolInvocationRecord
from nexus_runtimes.native.engine.cancellation import CancellationToken
from nexus_runtimes.native.engine.tools import execute_batch
from nexus_worker.__main__ import run_once
from sqlalchemy import select

from test_platform import database  # noqa: F401 (pytest fixture)
from test_native_runtime import FakeModel, call, registry, run_row, stack


def test_revocation_between_turns_stops_the_next_turns_tool_call(database):
    principal, tenant, _, run, grants = stack(database, ['echo'], shared=True)
    seen = []
    async def echo(args, context):
        seen.append(args['text'])
        with database() as db:
            revoke_resource_grant(db, principal, grants[0].id)
        return ToolResult('first result')
    # The Run's tool definitions were cached at start; the grant is checked again before every call.
    model = FakeModel([[call('echo', '{"text":"first"}')], [call('echo', '{"text":"second"}')], [ModelChunk('text', text='late')]])
    run_once(database, 'worker', model_factory=lambda _: model, registry_factory=lambda _: registry(echo))
    assert seen == ['first']  # the second turn never reached the handler
    with database() as db:
        invocations = db.scalars(select(ToolInvocationRecord).where(ToolInvocationRecord.run_id == run.id)).all()
        assert len(invocations) == 1
    assert run_row(database, run.id).error_code == 'run_authorization_denied'


def test_failed_grouped_commit_rolls_back_its_event_and_message(database, monkeypatch):
    principal, tenant, session, run, _ = stack(database)
    import nexus_platform.runs.store as store_module
    def failing_add_message(db, run, message):
        raise RuntimeError('storage failure')
    monkeypatch.setattr(store_module, 'add_message', failing_add_message)
    model = FakeModel([[ModelChunk('text', text='never stored')]])
    run_once(database, 'worker', model_factory=lambda _: model)
    with database() as db:
        assistant = db.scalars(select(MessageRecord).where(MessageRecord.session_id == session.id,
                                                           MessageRecord.role == 'assistant')).all()
        assert assistant == []
        kinds = [e.event_type for e in db.scalars(select(RunEventRecord).where(RunEventRecord.run_id == run.id))]
    assert 'model.completed' not in kinds  # rolled back with the message it was grouped with
    assert run_row(database, run.id).status == 'failed'


class _Gateway:
    def __init__(self, delays):
        self.delays, self.active, self.peak, self.log = delays, 0, 0, []

    async def execute(self, call, token):
        self.active += 1
        self.peak = max(self.peak, self.active)
        self.log.append(('start', call.name))
        try:
            await asyncio.sleep(self.delays[call.name])
        finally:
            self.active -= 1
            self.log.append(('end', call.name))
        return ToolResult(call.name)


async def _hook(phase, turn, name):
    pass


def _definitions():
    schema = {'type': 'object', 'properties': {}, 'additionalProperties': False}
    return (ToolDefinition('slow', '', schema, read_only=True, idempotent=True),
            ToolDefinition('fast', '', schema, read_only=True, idempotent=True),
            ToolDefinition('write', '', schema, side_effects=True))


def _collect(calls, gateway, parallel):
    async def run():
        token = CancellationToken()
        return [(index, result.data) async for index, result in
                execute_batch(calls, _definitions(), gateway, token, _hook, 1, parallel)]
    return asyncio.run(run())


CALLS = (ToolCall('1', 'slow', '{}'), ToolCall('2', 'fast', '{}'), ToolCall('3', 'write', '{}'), ToolCall('4', 'fast', '{}'))
DELAYS = {'slow': 0.05, 'fast': 0.0, 'write': 0.0}


def test_declared_reads_overlap_but_results_keep_model_order():
    gateway = _Gateway(DELAYS)
    results = _collect(CALLS, gateway, parallel=True)
    assert results == [(0, 'slow'), (1, 'fast'), (2, 'write'), (3, 'fast')]
    assert gateway.peak == 2  # the two reads overlapped
    # The mutation waits for every earlier read, and nothing overlaps it.
    write_start = gateway.log.index(('start', 'write'))
    assert gateway.log.index(('end', 'slow')) < write_start and gateway.log.index(('end', 'fast')) < write_start


def test_side_effect_tools_stay_serial_even_when_parallel_reads_are_enabled():
    gateway = _Gateway(DELAYS)
    _collect((ToolCall('1', 'write', '{}'), ToolCall('2', 'write', '{}')), gateway, parallel=True)
    assert gateway.peak == 1


def test_parallel_flag_off_keeps_every_call_serial():
    gateway = _Gateway(DELAYS)
    results = _collect(CALLS, gateway, parallel=False)
    assert [data for _, data in results] == ['slow', 'fast', 'write', 'fast']
    assert gateway.peak == 1
