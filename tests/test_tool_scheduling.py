"""Per-call tool scheduling (openspec 2026-11-07-tool-expansion, section 2)."""
import asyncio
import json

from nexus_core.runtime import ConcurrencyHint, ToolCall, ToolDefinition, ToolDisposition, ToolResult
from nexus_runtimes.native.engine.cancellation import CancellationToken
from nexus_runtimes.native.engine.tools import classify, execute_batch

SCHEMA = {'type': 'object', 'properties': {}}


class Recorder:
    """Fake gateway: records when each call starts and ends so overlap can be asserted."""

    def __init__(self, suspend=()):
        self.log, self.running, self.peak, self.suspend = [], 0, 0, set(suspend)

    def may_suspend(self, call):
        return call.name in self.suspend

    async def execute(self, call, token):
        self.log.append(('start', call.id))
        self.running += 1
        self.peak = max(self.peak, self.running)
        await asyncio.sleep(0.02)
        self.running -= 1
        self.log.append(('end', call.id))
        return ToolResult(call.id)


async def _hook(*args):
    return None


def _run(calls, definitions, gateway, parallel=True):
    async def go():
        return [(i, r.data) async for i, r in execute_batch(calls, definitions, gateway, CancellationToken(), _hook, 1, parallel)]
    return asyncio.run(go())


def _path_hint(mode):
    return lambda args: ConcurrencyHint(mode, args.get('path')) if mode == 'serial' else ConcurrencyHint(mode)


def _call(id, name, **arguments):
    return ToolCall(id, name, json.dumps(arguments))


def test_undeclared_tools_keep_the_old_rule():
    read = ToolDefinition('read', 'r', SCHEMA, read_only=True, idempotent=True)
    write = ToolDefinition('write', 'w', SCHEMA, side_effects=True)
    gateway = Recorder()
    _run([_call('1', 'read'), _call('2', 'read'), _call('3', 'write'), _call('4', 'read')], [read, write], gateway)
    assert gateway.peak == 2  # the two leading reads overlap; the write is a barrier
    assert gateway.log.index(('end', '2')) < gateway.log.index(('start', '3')) < gateway.log.index(('start', '4'))


def test_parallel_reads_by_argument_overlap_and_results_stay_in_model_order():
    read = ToolDefinition('read_file', 'r', SCHEMA, read_only=True, idempotent=True, concurrency=_path_hint('parallel'))
    gateway = Recorder()
    out = _run([_call(str(i), 'read_file', path=f'/w/{i}') for i in range(5)], [read], gateway)
    assert gateway.peak == 5 and [data for _, data in out] == ['0', '1', '2', '3', '4']


def test_same_key_writes_are_serialized_and_other_keys_overlap():
    write = ToolDefinition('write_file', 'w', SCHEMA, side_effects=True, risk='write', concurrency=_path_hint('serial'))
    gateway = Recorder()
    calls = [_call('a1', 'write_file', path='/w/a'), _call('a2', 'write_file', path='/w/a'),
             _call('b1', 'write_file', path='/w/b')]
    _run(calls, [write], gateway)
    assert gateway.log.index(('end', 'a1')) < gateway.log.index(('start', 'a2'))  # same path: in order, no overlap
    assert gateway.log.index(('start', 'b1')) < gateway.log.index(('end', 'a1'))  # another path overlaps


def test_exclusive_call_waits_for_the_group_and_runs_alone():
    read = ToolDefinition('read_file', 'r', SCHEMA, read_only=True, idempotent=True, concurrency=_path_hint('parallel'))
    run = ToolDefinition('exec', 'x', SCHEMA, side_effects=True, risk='write', concurrency=_path_hint('exclusive'))
    gateway = Recorder()
    _run([_call('1', 'read_file', path='a'), _call('2', 'read_file', path='b'), _call('3', 'exec'), _call('4', 'read_file', path='c')],
         [read, run], gateway)
    log = gateway.log
    assert log.index(('end', '1')) < log.index(('start', '3')) and log.index(('end', '2')) < log.index(('start', '3'))
    assert log.index(('end', '3')) < log.index(('start', '4'))


def test_parallel_option_off_runs_everything_in_order():
    read = ToolDefinition('read_file', 'r', SCHEMA, read_only=True, idempotent=True, concurrency=_path_hint('parallel'))
    gateway = Recorder()
    _run([_call('1', 'read_file', path='a'), _call('2', 'read_file', path='b')], [read], gateway, parallel=False)
    assert gateway.peak == 1


def test_bad_declarations_and_arguments_fall_back_to_exclusive():
    def boom(args):
        raise RuntimeError('broken')
    base = dict(read_only=True, idempotent=True)
    assert classify(_call('1', 'a'), ToolDefinition('a', 'd', SCHEMA, concurrency=boom, **base), None).mode == 'exclusive'
    assert classify(ToolCall('1', 'a', '{not json'), ToolDefinition('a', 'd', SCHEMA, concurrency=_path_hint('parallel'), **base), None).mode == 'exclusive'
    assert classify(ToolCall('1', 'a', '[1]'), ToolDefinition('a', 'd', SCHEMA, concurrency=_path_hint('parallel'), **base), None).mode == 'exclusive'
    assert classify(_call('1', 'a'), ToolDefinition('a', 'd', SCHEMA, concurrency=lambda args: ConcurrencyHint('serial'), **base), None).mode == 'exclusive'
    assert classify(_call('1', 'a'), ToolDefinition('a', 'd', SCHEMA, concurrency=lambda args: 'parallel', **base), None).mode == 'exclusive'
    assert classify(_call('1', 'ghost'), None, None).mode == 'exclusive'


def test_calls_that_may_ask_for_approval_never_join_a_group():
    write = ToolDefinition('write_file', 'w', SCHEMA, side_effects=True, risk='write', concurrency=_path_hint('serial'))
    gateway = Recorder(suspend={'write_file'})
    assert classify(_call('1', 'write_file', path='/w/a'), write, gateway).mode == 'exclusive'
    assert classify(_call('1', 'write_file', path='/w/a'), write, Recorder()).mode == 'serial'
    assert classify(_call('1', 'write_file', path='/w/a'), write, object()).mode == 'exclusive'  # gateway cannot say: be safe
    needs = ToolDefinition('write_file', 'w', SCHEMA, side_effects=True, risk='write', requires_approval=True, concurrency=_path_hint('serial'))
    assert classify(_call('1', 'write_file', path='/w/a'), needs, Recorder()).mode == 'exclusive'


def test_a_waiting_result_stops_the_batch_as_before():
    class Waiting(Recorder):
        async def execute(self, call, token):
            result = await super().execute(call, token)
            return ToolResult(result.data, disposition=ToolDisposition.WAIT_INPUT) if call.id == '1' else result
    ask = ToolDefinition('ask', 'a', SCHEMA)
    out = _run([_call('1', 'ask'), _call('2', 'ask')], [ask], Waiting())
    assert [data for _, data in out] == ['1']


# ---------------------------------------------------------------- gateway.may_suspend

def _real_gateway(name, access):
    from nexus_tools.gateway import AuthorizedToolGateway
    from nexus_tools.registry import RegisteredTool, ToolRegistry

    class Port:
        async def authorize(self, *a): return 'b'
        async def start(self, *a): return 'i'
        async def finish(self, *a): return None
        async def denied(self, *a): return None
    tools = ToolRegistry()
    schema = {'type': 'object', 'properties': {'command': {'type': 'string'}}}
    tools.register(RegisteredTool(ToolDefinition(name, 'd', schema, side_effects=True, risk='write'),
                                  lambda args, ctx: ToolResult('ok'), lambda r: r.data))
    return AuthorizedToolGateway(tools, Port(), {name: 'v1'}, run_id='r', session_id='s', tenant_id='t', tool_access=access)


def test_may_suspend_follows_access_level_and_guard_findings():
    assert _real_gateway('write_file', 'standard').may_suspend(_call('1', 'write_file', command='x')) is False
    assert _real_gateway('write_file', 'strict').may_suspend(_call('1', 'write_file', command='x')) is True
    assert _real_gateway('bash', 'standard').may_suspend(_call('1', 'bash', command='ls')) is False
    assert _real_gateway('bash', 'standard').may_suspend(_call('1', 'bash', command='rm -rf build')) is True
    assert _real_gateway('write_file', 'strict').may_suspend(_call('1', 'ghost')) is False
