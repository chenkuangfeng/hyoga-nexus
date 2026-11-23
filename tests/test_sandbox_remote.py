"""Remote command integration, gateway authorization and live profile policy."""
import asyncio
import json
from dataclasses import replace

import httpx
import pytest
from fastapi.testclient import TestClient

from nexus_api import sandbox_gateway
from nexus_core.sandbox import ExecResult, SandboxError
from nexus_sandbox.backends.remote import RemoteExecutor, decode_result
from nexus_sandbox.remote_runner import execute, parse_execution
from nexus_sandbox.settings import SandboxSettings, load_config, save_profile_policy


def _body(**changes):
    return {
        'id': 'a' * 32, 'profile': 'sandbox-node', 'tenant_id': 'tenant', 'session_id': 'session',
        'command': 'printf ok', 'cwd': '/workspace', 'timeout_seconds': 10, 'output_limit': 100,
        'env': None, 'stdin': None, 'network': 'none',
        'limits': {'cpus': 1, 'memory_mb': 512, 'pids': 128},
    } | changes


def _settings(tmp_path):
    return SandboxSettings(enabled=True, backend='docker', profile='sandbox-node', workspace_root=str(tmp_path))


def test_ssh_uses_pinned_host_and_fixed_runner():
    settings = SandboxSettings(backend='ssh', remote_profile='linux-node', ssh_host='host.example.test',
                               ssh_user='sandbox', ssh_identity_file='/key', ssh_known_hosts='/known_hosts')
    argv = RemoteExecutor(settings, 'tenant', 'session').ssh_arguments()
    assert 'StrictHostKeyChecking=yes' in argv
    assert 'UserKnownHostsFile=/known_hosts' in argv
    assert argv[-4:] == ['host.example.test', 'python3', '-m', 'nexus_sandbox.remote_runner']


def test_remote_rejects_invalid_scope_and_resource_mismatch(tmp_path):
    with pytest.raises(SandboxError, match='sandbox_remote_request_invalid'):
        parse_execution(json.dumps(_body(session_id='../outside')).encode())
    request = parse_execution(json.dumps(_body(limits={'cpus': 2, 'memory_mb': 512, 'pids': 128})).encode())
    with pytest.raises(SandboxError, match='sandbox_remote_policy_mismatch'):
        asyncio.run(execute(request, _settings(tmp_path), backend='docker'))
    assert not (tmp_path / 'tenant').exists()


def test_remote_rejects_oversized_result():
    with pytest.raises(SandboxError, match='sandbox_remote_response_invalid'):
        decode_result(json.dumps({
            'exit_code': 0, 'timed_out': False, 'stdout': 'a' * 1024, 'stderr': '',
            'stdout_truncated': False, 'stderr_truncated': False, 'duration_ms': 5,
        }).encode(), 100)


def test_managed_client_and_gateway_round_trip(tmp_path, monkeypatch):
    token_path = tmp_path / 'token'
    token_path.write_text('t' * 32)
    settings = _settings(tmp_path)
    monkeypatch.setattr(sandbox_gateway, 'section', lambda _: {
        'token_file': str(token_path), 'profiles': [settings.profile],
    })
    from nexus_sandbox.settings import SandboxConfig
    monkeypatch.setattr(sandbox_gateway, 'load_config', lambda: SandboxConfig(
        enabled=True, default_profile=settings.profile, profiles={settings.profile: settings},
    ))
    commands = []

    async def run_command(request, selected, *, backend):
        assert selected == settings and backend == 'docker'
        commands.append(request)
        return ExecResult(0, False, 'ok', '', False, False, 5)

    monkeypatch.setattr(sandbox_gateway, 'execute', run_command)
    client_constructor = httpx.AsyncClient
    with TestClient(sandbox_gateway.app) as client:
        assert client.post('/v1/executions', json=_body()).status_code == 401
        headers = {'Authorization': 'Bearer ' + 't' * 32}
        assert client.post('/v1/executions', json=_body(tenant_id='../x'), headers=headers).status_code == 400
        assert client.delete('/v1/executions/' + 'a' * 32, headers=headers).status_code == 204
        assert client.post('/v1/executions', json=_body(), headers=headers).status_code == 409
        monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: client_constructor(
            transport=httpx.ASGITransport(app=sandbox_gateway.app), **kwargs,
        ))
        target = replace(settings, backend='managed', remote_profile=settings.profile,
                         endpoint='https://sandbox.example.test', token_file=str(token_path))
        result = asyncio.run(RemoteExecutor(target, 'tenant', 'session').run(
            'printf ok', cwd='/workspace', timeout_seconds=10, output_limit=100,
        ))
    assert result.stdout == 'ok'
    assert len(commands) == 1 and commands[0].session_id == 'session'


def test_profile_policy_is_live_and_preserves_deployment_settings(tmp_path):
    config = tmp_path / 'nexus.toml'
    config.write_text(f"""
[sandbox]
enabled = true
workspace_root = "{tmp_path}"
[sandbox.profiles.sandbox-node]
type = "docker"
image = "runtime:test"
""")
    settings = load_config(config).get()
    save_profile_policy(settings, {'paused': True, 'exec_timeout_max_seconds': 45})
    updated = load_config(config).get()
    assert updated.paused and updated.exec_timeout_max_seconds == 45
    assert updated.image == 'runtime:test'
    assert not load_config(config, include_policies=False).get().paused


def test_ssh_runner_executes_in_real_bwrap_when_available(tmp_path):
    import subprocess
    import sys

    from test_sandbox import _bwrap_works

    if not _bwrap_works():
        pytest.skip('bwrap is unavailable')
    (tmp_path / 'configs').mkdir()
    (tmp_path / 'configs' / 'nexus.toml').write_text(f"""
[sandbox]
enabled = true
workspace_root = "{tmp_path / 'shared'}"
[sandbox.profiles.sandbox-node]
type = "bwrap"
""")
    result = subprocess.run(
        [sys.executable, '-m', 'nexus_sandbox.remote_runner'], cwd=tmp_path,
        input=json.dumps(_body(limits=None, command='printf ok > /outputs/result.txt; cat /outputs/result.txt')).encode(),
        capture_output=True, timeout=30, check=True,
    )
    assert decode_result(result.stdout, 100).stdout == 'ok'
    path = tmp_path / 'shared' / 'tenant' / 'session' / 'outputs' / 'result.txt'
    assert path.read_text() == 'ok'
