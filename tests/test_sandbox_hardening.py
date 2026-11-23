"""Adversarial snapshots, persistent request recovery and bounded provider execution."""
import asyncio
import io
import json
import os
import shutil
import tarfile
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from nexus_core.sandbox import SandboxError
from nexus_sandbox import leases, transfer
from nexus_sandbox.lifecycle import Journal, drain
from nexus_sandbox.providers import provider_identity, recover_provider


def roots(tmp_path):
    result = {name: tmp_path / name for name in transfer.ROOTS}
    for path in result.values():
        path.mkdir()
    return result


def test_snapshot_round_trip_preserves_binary_and_deletions(tmp_path):
    source = tmp_path / 'source'
    source.mkdir()
    original = roots(source)
    (original['workspace'] / 'data.bin').write_bytes(b'\0\xffbinary')
    (original['outputs'] / 'report.txt').write_text('report')
    archive = tmp_path / 'snapshot.tar'
    transfer.pack(original, archive)
    target = tmp_path / 'target'
    target.mkdir()
    previous = roots(target)
    (previous['workspace'] / 'deleted.txt').write_text('old')
    transfer.publish(archive, target)
    assert (target / 'workspace' / 'data.bin').read_bytes() == b'\0\xffbinary'
    assert not (target / 'workspace' / 'deleted.txt').exists()


@pytest.mark.parametrize('name,kind', [
    ('../outside', tarfile.REGTYPE), ('/workspace/escape', tarfile.REGTYPE),
    ('workspace/link', tarfile.SYMTYPE), ('workspace/pipe', tarfile.FIFOTYPE),
    ('workspace/hard', tarfile.LNKTYPE),
])
def test_untrusted_snapshot_never_publishes_partial_files(tmp_path, name, kind):
    base = tmp_path / 'base'
    base.mkdir()
    current = roots(base)
    (current['workspace'] / 'keep').write_text('old')
    archive = tmp_path / 'malicious.tar'
    with tarfile.open(archive, 'w') as stream:
        entry = tarfile.TarInfo(name)
        entry.type, entry.linkname = kind, '/etc/passwd'
        stream.addfile(entry)
    with pytest.raises((ValueError, OSError)):
        transfer.publish(archive, base)
    assert (base / 'workspace' / 'keep').read_text() == 'old'


def test_snapshot_pack_refuses_linked_ancestors_and_limits(tmp_path):
    original = roots(tmp_path)
    (original['workspace'] / 'link').symlink_to('/etc/passwd')
    with pytest.raises(ValueError):
        transfer.pack(original, tmp_path / 'out.tar')
    (original['workspace'] / 'link').unlink()
    (original['workspace'] / 'huge').write_bytes(b'x' * 100)
    with pytest.raises(ValueError):
        transfer.pack(original, tmp_path / 'out.tar', limit=20)


def test_journal_ownership_and_duplicate_requests_survive_restart(tmp_path):
    journal = Journal(tmp_path)
    journal.reserve('a' * 32, 'cloud')
    with pytest.raises(SandboxError):
        Journal(tmp_path)
    journal.close()
    restarted = Journal(tmp_path)
    try:
        with pytest.raises(SandboxError, match='sandbox_execution_already_exists'):
            restarted.reserve('a' * 32, 'cloud')
        assert len(restarted.pending()) == 1
    finally:
        restarted.close()


def test_recovery_discovers_unknown_create_and_retains_tombstone_through_ttl(tmp_path, monkeypatch):
    from nexus_sandbox import providers
    key = tmp_path / 'key'
    key.write_text('secret')
    config = {'type': 'e2b', 'template': 'base', 'revision': 'r1', 'domain': 'e2b.app',
              'api_key_file': str(key)}
    journal = Journal(tmp_path / 'journal')
    journal.reserve('a' * 32, 'cloud')
    record = journal.write('a' * 32, policy=provider_identity(config), expires_at=time.time() + 300)
    killed = []
    class Paginator:
        has_next = True
        async def next_items(self):
            self.has_next = False
            return [SimpleNamespace(sandbox_id='recovered')]
    async def kill(sandbox_id, **kwargs):
        killed.append(sandbox_id)
    monkeypatch.setattr(providers.AsyncSandbox, 'list', lambda **kwargs: Paginator())
    monkeypatch.setattr(providers.AsyncSandbox, 'kill', kill)
    try:
        asyncio.run(recover_provider(record, config, journal))
        assert killed == ['recovered'] and journal.pending()
        record = journal.write('a' * 32, expires_at=0)
        asyncio.run(recover_provider(record, config, journal))
        assert not journal.pending()
    finally:
        journal.close()


def test_cleanup_drains_through_repeated_cancellation():
    async def scenario():
        completed = []
        async def work():
            await asyncio.sleep(.05)
            completed.append(True)
        task = asyncio.create_task(drain(work()))
        await asyncio.sleep(.01)
        task.cancel()
        await asyncio.sleep(.01)
        task.cancel()
        await task
        assert completed == [True]
    asyncio.run(scenario())


def test_reaper_cannot_remove_another_process_execution(tmp_path):
    async def scenario():
        async with leases.hold(tmp_path, 'container'):
            assert leases.try_reap(tmp_path, 'container', 0) is None
        assert leases.try_reap(tmp_path, 'container', 60) is None
        lock = leases.try_reap(tmp_path, 'container', 0)
        assert lock is not None
        lock.close()
    asyncio.run(scenario())


def test_real_provider_runner_bounds_output_and_keeps_partial_timeout_artifact(tmp_path):
    from test_sandbox import _bwrap_works, bwrap_settings
    from nexus_sandbox.manager import SandboxManager
    if not _bwrap_works():
        pytest.skip('bwrap unavailable')
    settings = bwrap_settings(tmp_path / 'sandbox')
    session = SandboxManager(settings).session('tenant', 'session')
    import sys
    session.executor._inner.envs = Path(sys.executable).resolve().parent.parent
    workspace = session.files.roots['/workspace']
    control = workspace / 'control'
    control.mkdir()
    package = Path(transfer.__file__).parent
    for target, source in [('runner.py', package / 'provider_runner.py'),
                           ('nexus_transfer.py', package / 'transfer.py'),
                           ('nexus_output.py', package / 'backends' / 'output.py')]:
        shutil.copyfile(source, control / target)
    (control / 'request.json').write_text(json.dumps({
        'command': "printf artifact > /outputs/partial; python3 -c 'print(\"x\"*3000000)'; sleep 30",
        'cwd': '/workspace', 'timeout_seconds': 1, 'output_limit': 1000,
        'env': None, 'stdin': None, 'transfer_limit': 5_000_000,
    }))
    result = asyncio.run(session.exec(
        'mkdir /tmp/control; cp /workspace/control/* /tmp/control/; '
        'PYTHONHOME=/skill_envs /skill_envs/bin/python3.11 /tmp/control/runner.py /tmp/control && cat /tmp/control/result.json',
        cwd='/workspace', timeout_seconds=20,
    ))
    assert result.exit_code == 0, result.stderr
    data = json.loads(result.stdout)
    assert data['timed_out'] and data['stdout_truncated'] and len(data['stdout']) < 1300
    assert (session.files.roots['/outputs'] / 'partial').read_text() == 'artifact'


def test_encrypted_provider_configuration_never_returns_or_stores_plaintext(tmp_path, monkeypatch):
    from cryptography.fernet import Fernet
    from nexus_api import gateway_provider_config as config
    cipher = Fernet(Fernet.generate_key())
    monkeypatch.setattr(config, 'cipher', lambda: cipher)
    body = {'type': 'cubesandbox', 'template': 'base', 'domain': 'cube.example.test',
            'revision': '2026-11', 'api_key': 'secret-provider-key'}
    saved = config.save_provider(tmp_path, 'cloud', body, None)
    assert b'secret-provider-key' not in (tmp_path / 'provider-cloud.encrypted').read_bytes()
    public = config.public_provider(saved)
    assert 'api_key' not in public and public['has_api_key']
    restored = config.load_providers(tmp_path, {'cloud': object()}, {})
    assert restored['cloud']['api_key'] == 'secret-provider-key'
    rotated = config.save_provider(tmp_path, 'cloud', body | {'api_key': ''}, restored['cloud'])
    assert rotated['api_key'] == 'secret-provider-key'


def test_policy_digest_changes_with_node_template_and_limits(tmp_path, monkeypatch):
    from nexus_sandbox.gateway_state import GatewayState
    from nexus_sandbox.settings import SandboxSettings
    from dataclasses import replace
    settings = SandboxSettings(enabled=True, backend='docker')
    provider = {'type': 'e2b', 'template': 'base', 'domain': 'e2b.app', 'revision': 'v1'}
    state = GatewayState(tmp_path / 'node', {'cloud': settings}, {'cloud': provider})
    try:
        first = asyncio.run(state.capabilities('cloud', settings))['policy_digest']
        provider['revision'] = 'v2'
        second = asyncio.run(state.capabilities('cloud', settings))['policy_digest']
        assert first != second
        assert second != asyncio.run(state.capabilities('cloud', replace(settings, memory_mb=1024)))['policy_digest']
    finally:
        state.journal.close()


def test_provider_create_cancellation_is_reconciled_and_reclaimed(tmp_path, monkeypatch):
    from nexus_sandbox import providers
    from nexus_sandbox.remote_runner import parse_execution
    from nexus_sandbox.settings import SandboxSettings
    key = tmp_path / 'key'
    key.write_text('secret')
    config = {'type': 'e2b', 'template': 'base', 'revision': 'v1', 'domain': 'e2b.app',
              'api_key_file': str(key)}
    from test_sandbox_remote import _body
    request = parse_execution(json.dumps(_body()).encode())
    settings = SandboxSettings(enabled=True, backend='docker', workspace_root=str(tmp_path))
    journal = Journal(tmp_path / 'journal')
    journal.reserve(request.id, request.profile)
    killed = []

    async def create(**kwargs):
        await asyncio.sleep(.05)
        async def kill(**kwargs):
            killed.append(True)
        return SimpleNamespace(sandbox_id='late-instance', kill=kill)
    monkeypatch.setattr(providers.AsyncSandbox, 'create', create)
    async def scenario():
        task = asyncio.create_task(providers.execute_provider(request, settings, config, journal=journal))
        await asyncio.sleep(.01)
        task.cancel()
        await asyncio.sleep(.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    try:
        asyncio.run(scenario())
        assert killed == [True]
        assert journal.get(request.id)['state'] == 'finished'
    finally:
        journal.close()


def test_file_reader_rejects_fifo_without_waiting(tmp_path):
    from nexus_sandbox.files import HostFileStore
    store = HostFileStore(tmp_path / 'w', tmp_path / 'o', quota_bytes=1000)
    os.mkfifo(tmp_path / 'w' / 'pipe')
    with pytest.raises(SandboxError):
        asyncio.run(store.read_file('/workspace/pipe', start_line=1, max_lines=5))


def test_bwrap_cgroup_requires_real_delegated_v2_controllers(tmp_path):
    from dataclasses import replace
    from nexus_sandbox.cgroups import CommandCgroup
    from nexus_sandbox.settings import SandboxSettings
    settings = SandboxSettings(backend='bwrap', cgroup_root=str(tmp_path))
    with pytest.raises(SandboxError, match='sandbox_cgroup_unavailable'):
        CommandCgroup(settings)


def test_xfs_quota_reserves_project_id_before_setting_kernel_limits(tmp_path, monkeypatch):
    from nexus_sandbox.disk_quota import ensure
    from nexus_sandbox.settings import SandboxSettings
    import subprocess
    mount = tmp_path / 'mount'
    base = mount / 'data'
    session = base / 'tenant' / 'session'
    session.mkdir(parents=True)
    settings = SandboxSettings(workspace_root=str(base), quota_mount=str(mount),
                               quota_project_start=500000, quota_inodes=1000)
    calls = []
    def execute(argv, **kwargs):
        calls.append(argv)
        assert 'shell' not in kwargs
        records = json.loads((base / '_quota_projects.json').read_text())
        assert records[str(session)]['id'] == 500000
        return subprocess.CompletedProcess(argv, 0, b'', b'')
    monkeypatch.setattr(subprocess, 'run', execute)
    ensure(settings, session)
    ensure(settings, session)
    assert all('500000' in call[3] for call in calls)
    assert 'ihard=1000' in calls[1][3] and 'bhard=512m' in calls[1][3]


def test_interrupted_snapshot_publication_rolls_back_before_next_execution(tmp_path):
    original = roots(tmp_path)
    (original['workspace'] / 'old').write_text('previous')
    staging = tmp_path / '.sync-crash'
    staging.mkdir()
    (staging / '.publication').write_text('prepared')
    os.replace(tmp_path / 'workspace', staging / 'old-workspace')
    (tmp_path / 'workspace').mkdir()
    (tmp_path / 'workspace' / 'new').write_text('uncommitted')
    transfer.recover_publication(tmp_path)
    assert (tmp_path / 'workspace' / 'old').read_text() == 'previous'
    assert not (tmp_path / 'workspace' / 'new').exists()
    assert not staging.exists()


def test_provider_download_stops_at_limit_and_keeps_credentials_out_of_url(tmp_path, monkeypatch):
    import httpx
    from nexus_sandbox import providers
    chunks = []
    closed = []
    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            for _ in range(10):
                chunks.append(True)
                yield b'x' * 65536
        async def aclose(self):
            closed.append(True)
    def handler(request):
        assert 'secret' not in str(request.url)
        assert request.headers['x-access-token'] == 'secret'
        return httpx.Response(200, stream=Stream())
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: original(
        transport=httpx.MockTransport(handler), **kwargs,
    ))
    sandbox = SimpleNamespace(envd_api_url='https://vm.example.test',
                              connection_config=SimpleNamespace(sandbox_headers={'X-Access-Token': 'secret'}))
    with pytest.raises(SandboxError, match='sandbox_transfer_limit_exceeded'):
        asyncio.run(providers.download(sandbox, '/result.tar', tmp_path / 'result', 10))
    assert len(chunks) == 1 and closed
