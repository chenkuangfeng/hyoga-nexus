"""Sandbox tools through the real gateway (openspec 2026-11-07-tool-expansion, section 4)."""
import asyncio
import json
from uuid import uuid4

import pytest

from nexus_core.native import SANDBOX_TOOL_NAMES
from nexus_core.runtime import ToolCall
from nexus_runtimes.native.engine.cancellation import CancellationToken
from nexus_runtimes.native.engine.tools import execute_batch
from nexus_sandbox.manager import SandboxManager
from nexus_sandbox.settings import SandboxSettings
from nexus_tools.builtins import builtins
from nexus_tools.builtins.services import RunServices
from nexus_tools.gateway import AuthorizedToolGateway


class Port:
    def __init__(self):
        self.approvals = []

    async def authorize(self, name, version):
        return 'b-' + name

    async def start(self, call, binding_id):
        return str(uuid4())

    async def finish(self, *args):
        return None

    async def denied(self, name):
        return None

    async def approval(self, call, **kwargs):
        self.approvals.append(call.name)
        return call.arguments


class Store:
    pass


@pytest.fixture
def env(tmp_path):
    settings = SandboxSettings(enabled=True, backend='local', workspace_root=str(tmp_path / 'sbx'), allow_local=True)
    session = SandboxManager(settings).session('t1', 's1', default_timeout=5, output_limit=4000)

    def gateway(access='standard', sandbox=session, port=None):
        port = port or Port()
        return AuthorizedToolGateway(builtins(), port, {name: 'v1' for name in SANDBOX_TOOL_NAMES}, run_id='r', session_id='s',
                                     tenant_id='t', services=RunServices(Store(), {}, sandbox), tool_access=access), port

    def call(gw, name, **arguments):
        return asyncio.run(gw.execute(ToolCall(str(uuid4()), name, json.dumps(arguments)), CancellationToken()))
    return gateway, call, tmp_path


def test_files_and_commands_roundtrip_without_host_paths(env):
    gateway, call, tmp_path = env
    gw, _ = gateway()
    assert 'wrote 12 bytes' in call(gw, 'sandbox_write_file', path='/workspace/app/main.py', content='print("hi")\n').data
    read = call(gw, 'sandbox_read_file', path='/workspace/app/main.py')
    assert 'print("hi")' in read.data and 'end of file' in read.data
    assert 'edited' in call(gw, 'sandbox_edit_file', path='/workspace/app/main.py', old='hi', new='there').data
    assert 'there' in call(gw, 'sandbox_search_files', query='there', path='/workspace').data
    assert '/workspace/app/' in call(gw, 'sandbox_list_files', path='/workspace').data
    executed = call(gw, 'sandbox_exec', command='ls app && echo done')
    assert 'exit_code: 0' in executed.data and 'main.py' in executed.data and 'done' in executed.data
    for result in (read, executed, call(gw, 'sandbox_list_files', path='/')):
        assert str(tmp_path) not in result.data


def test_errors_are_stable_codes_the_model_can_act_on(env):
    gateway, call, _ = env
    gw, _ = gateway()
    call(gw, 'sandbox_write_file', path='/workspace/a.txt', content='x x')
    ambiguous = call(gw, 'sandbox_edit_file', path='/workspace/a.txt', old='x', new='y')
    assert ambiguous.error_code == 'sandbox_edit_ambiguous' and '2 matches' in ambiguous.data
    assert call(gw, 'sandbox_read_file', path='/etc/passwd').error_code == 'sandbox_path_invalid'
    assert call(gw, 'sandbox_read_file', path='/workspace/missing').error_code == 'sandbox_not_found'
    timed_out = call(gw, 'sandbox_exec', command='sleep 20', timeout_seconds=1)
    assert timed_out.error_code == 'sandbox_exec_timeout' and 'timed out' in timed_out.data


def test_tools_fail_closed_without_a_sandbox_session(env):
    gateway, call, _ = env
    gw, _ = gateway(sandbox=None)
    assert call(gw, 'sandbox_exec', command='true').error_code == 'sandbox_unavailable'


def test_access_levels_apply_to_sandbox_tools(env):
    gateway, call, _ = env
    read_only, _ = gateway('read_only')
    assert {d.name for d in asyncio.run(read_only.definitions())} == {'sandbox_list_files', 'sandbox_read_file', 'sandbox_search_files', 'sandbox_job_wait'}
    assert call(read_only, 'sandbox_exec', command='true').error_code == 'tool_authorization_denied'
    standard, port = gateway('standard')
    call(standard, 'sandbox_write_file', path='/workspace/a.txt', content='x')
    call(standard, 'sandbox_exec', command='true')
    assert port.approvals == []  # isolated, no network: writes and commands run without asking
    strict, port = gateway('strict')
    call(strict, 'sandbox_write_file', path='/workspace/a.txt', content='x')
    call(strict, 'sandbox_exec', command='true')
    assert port.approvals == ['sandbox_write_file', 'sandbox_exec']


def test_dangerous_commands_ask_even_at_standard_level(env):
    gateway, call, _ = env
    gw, port = gateway()
    call(gw, 'sandbox_exec', command='rm -rf build')
    assert port.approvals == ['sandbox_exec']


def test_risk_and_scheduling_declarations():
    registry = builtins()
    risks = {name: registry.get(name, 'v1').definition.risk for name in SANDBOX_TOOL_NAMES}
    assert risks == {'sandbox_list_files': 'read', 'sandbox_read_file': 'read', 'sandbox_search_files': 'read',
                     'sandbox_write_file': 'write', 'sandbox_edit_file': 'write', 'sandbox_exec': 'write',
                     'sandbox_exec_async': 'write', 'sandbox_job_wait': 'read', 'sandbox_job_cancel': 'write'}
    assert all(registry.get(name, 'v1').definition.group == 'sandbox' for name in SANDBOX_TOOL_NAMES)
    write = registry.get('sandbox_write_file', 'v1').definition
    assert write.concurrency({'path': '/workspace/./a'}).key == '/workspace/a'
    assert write.concurrency({'path': '/workspace/../x'}).mode == 'exclusive'
    assert registry.get('sandbox_exec', 'v1').definition.timeout_seconds >= 135


def test_same_path_calls_in_one_batch_run_in_order_and_other_paths_overlap(env):
    gateway, _, _ = env
    gw, _ = gateway()
    definitions = asyncio.run(gw.definitions())
    calls = [ToolCall('1', 'sandbox_write_file', json.dumps({'path': '/workspace/a.txt', 'content': 'one'})),
             ToolCall('2', 'sandbox_read_file', json.dumps({'path': '/workspace/a.txt'})),
             ToolCall('3', 'sandbox_write_file', json.dumps({'path': '/workspace/b.txt', 'content': 'two'}))]

    async def hook(*args):
        return None

    async def go():
        return [(i, r.data) async for i, r in execute_batch(calls, definitions, gw, CancellationToken(), hook, 1, True)]
    out = asyncio.run(go())
    assert [i for i, _ in out] == [0, 1, 2] and 'one' in out[1][1]  # the read of a.txt saw the write before it


# ---------------------------------------------------------------- background jobs

def test_background_command_runs_reports_output_and_exit_code(env):
    gateway, call, tmp_path = env
    gw, _ = gateway()
    started = call(gw, 'sandbox_exec_async', command='echo first; sleep 1; echo second; exit 3')
    assert started.error_code is None
    job = started.data.split()[3].rstrip('.')
    running = call(gw, 'sandbox_job_wait', job_id=job, wait_seconds=0)
    assert 'running' in running.data
    done = call(gw, 'sandbox_job_wait', job_id=job, wait_seconds=10)
    assert 'finished with exit_code 3' in done.data and 'first' in done.data and 'second' in done.data
    assert str(tmp_path) not in done.data


def test_background_command_runs_in_the_requested_directory_and_reports_a_bad_one(env):
    gateway, call, _ = env
    gw, _ = gateway()
    call(gw, 'sandbox_write_file', path='/workspace/sub/marker.txt', content='x')
    job = call(gw, 'sandbox_exec_async', command='ls', cwd='/workspace/sub').data.split()[3].rstrip('.')
    assert 'marker.txt' in call(gw, 'sandbox_job_wait', job_id=job, wait_seconds=10).data
    missing = call(gw, 'sandbox_exec_async', command='ls', cwd='/workspace/nope').data.split()[3].rstrip('.')
    assert 'finished with exit_code 1' in call(gw, 'sandbox_job_wait', job_id=missing, wait_seconds=10).data
    assert call(gw, 'sandbox_exec_async', command='ls', cwd='/outputs').error_code == 'sandbox_path_invalid'


def test_cancel_kills_the_whole_process_tree(env):
    gateway, call, tmp_path = env
    gw, _ = gateway()
    marker = tmp_path / 'sbx' / 't1' / 's1' / 'workspace' / 'late.txt'
    job = call(gw, 'sandbox_exec_async', command=f'(sleep 3; echo late > {marker}) & sleep 60').data.split()[3].rstrip('.')
    cancelled = call(gw, 'sandbox_job_cancel', job_id=job)
    assert 'cancelled' in cancelled.data
    import time
    time.sleep(3.5)
    assert not marker.exists()
    assert 'cancelled' in call(gw, 'sandbox_job_wait', job_id=job, wait_seconds=0).data


def test_job_limits_ids_and_cleanup_when_the_run_ends(env):
    gateway, call, _ = env
    gw, _ = gateway()
    jobs = [call(gw, 'sandbox_exec_async', command='sleep 30').data.split()[3].rstrip('.') for _ in range(4)]
    assert call(gw, 'sandbox_exec_async', command='sleep 30').error_code == 'sandbox_too_many_jobs'
    assert call(gw, 'sandbox_job_wait', job_id='j0000000000', wait_seconds=0).error_code == 'sandbox_job_not_found'
    assert call(gw, 'sandbox_job_cancel', job_id='../etc').error_code in ('sandbox_job_not_found', 'tool_arguments_invalid')
    session = gw.services.sandbox
    assert asyncio.run(session.close_jobs()) == 4
    assert all('cancelled' in call(gw, 'sandbox_job_wait', job_id=job, wait_seconds=0).data for job in jobs)
    assert asyncio.run(session.close_jobs()) == 0


def test_background_command_past_its_timeout_is_killed_with_code_124(env):
    gateway, call, _ = env
    gw, _ = gateway()
    job = call(gw, 'sandbox_exec_async', command='echo start; sleep 30', timeout_seconds=1).data.split()[3].rstrip('.')
    done = call(gw, 'sandbox_job_wait', job_id=job, wait_seconds=10)
    assert 'exit_code 124' in done.data and 'start' in done.data
