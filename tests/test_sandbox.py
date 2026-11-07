"""Sandbox package: settings, virtual paths, file store, executors, manager (openspec 2026-11-07-tool-expansion, sections 3-4).

The docker backend is exercised against a recording stand-in for the `docker` CLI (it runs the `exec` payload
locally). The real daemon is covered by the isolation acceptance (`python -m nexus_worker --sandbox-check`).
"""
import asyncio
import json
import os
import stat
import sys
import textwrap

import pytest

from nexus_core.deployment import DeploymentConfigError
from nexus_core.sandbox import SandboxError
from nexus_sandbox import acceptance, paths
from nexus_sandbox.backends.docker import DockerBackend, container_name
from nexus_sandbox.backends.output import Sink
from nexus_sandbox.backends.bwrap import BwrapBackend, BwrapExecutor
from nexus_sandbox.files import HostFileStore
from nexus_sandbox.manager import SandboxManager
from nexus_sandbox.settings import SandboxSettings, load_settings


def run(coro):
    return asyncio.run(coro)


def local_settings(tmp_path, **overrides):
    return SandboxSettings(enabled=True, backend='local', workspace_root=str(tmp_path / 'sbx'), allow_local=True, **overrides)


# ------------------------------------------------------------------ settings

def _write_config(tmp_path, body):
    path = tmp_path / 'nexus.toml'
    path.write_text(body, encoding='utf-8')
    return path


def test_settings_default_to_a_disabled_local_profile(tmp_path):
    settings = load_settings(_write_config(tmp_path, ''))
    assert settings.enabled is False and settings.backend == 'local' and settings.profile == 'local'
    assert settings.network == 'none' and settings.allow_local is False


@pytest.mark.parametrize('body', ['[sandbox]\nbackend = "vm"', '[sandbox]\nmemory_mb = 1', '[sandbox]\nnetwork = "host"',
                                  '[sandbox]\nenabled = "yes"', '[sandbox]\ncpus = true', '[sandbox]\nsurprise = 1',
                                  '[sandbox]\nimage = "a b"'])
def test_invalid_settings_are_rejected_without_echoing_values(tmp_path, body):
    with pytest.raises(DeploymentConfigError) as error:
        load_settings(_write_config(tmp_path, body))
    assert 'vm' not in str(error.value) and 'host' not in str(error.value)


def test_valid_settings_are_read(tmp_path):
    settings = load_settings(_write_config(tmp_path, '[sandbox]\nenabled = true\ncpus = 2\nmemory_mb = 1024\nnetwork = "bridge"'))
    assert (settings.enabled, settings.cpus, settings.memory_mb, settings.network) == (True, 2.0, 1024, 'bridge')


# ------------------------------------------------------------------ paths

@pytest.fixture
def roots(tmp_path):
    workspace, outputs = tmp_path / 'w', tmp_path / 'o'
    workspace.mkdir(), outputs.mkdir()
    return {'/workspace': workspace, '/outputs': outputs}


@pytest.mark.parametrize('bad', ['', 'relative.txt', '/etc/passwd', '/workspace/../etc', '/workspace/a/../../x', '/work', '/workspace\x00',
                                 '/' + 'a' * 2000])
def test_invalid_virtual_paths_are_refused(roots, bad):
    with pytest.raises(SandboxError) as error:
        paths.resolve(bad, roots)
    assert error.value.code == 'sandbox_path_invalid'


def test_valid_paths_resolve_inside_their_root(roots):
    assert paths.resolve('/workspace/a/./b.txt', roots) == roots['/workspace'].resolve() / 'a' / 'b.txt'
    assert paths.resolve('/outputs', roots) == roots['/outputs'].resolve()
    assert paths.virtual_of(roots['/workspace'] / 'a' / 'b.txt', roots) == '/workspace/a/b.txt'


def test_symbolic_links_leaving_the_root_are_refused(roots, tmp_path):
    (tmp_path / 'secret.txt').write_text('host secret')
    (roots['/workspace'] / 'link').symlink_to(tmp_path / 'secret.txt')
    (roots['/workspace'] / 'dirlink').symlink_to(tmp_path)
    for virtual in ('/workspace/link', '/workspace/dirlink/secret.txt', '/workspace/dirlink/new.txt'):
        with pytest.raises(SandboxError) as error:
            paths.resolve(virtual, roots)
        assert error.value.code == 'sandbox_path_invalid'
    (roots['/workspace'] / 'inside').write_text('x')
    (roots['/workspace'] / 'ok').symlink_to(roots['/workspace'] / 'inside')
    assert paths.resolve('/workspace/ok', roots, must_exist=True).name == 'ok'


# ------------------------------------------------------------------ file store

@pytest.fixture
def store(tmp_path):
    return HostFileStore(tmp_path / 'w', tmp_path / 'o', quota_bytes=10_000)


def test_write_read_append_edit_roundtrip(store):
    assert run(store.write_file('/workspace/dir/a.txt', 'one\ntwo\nthree\n', append=False)) == 14
    run(store.write_file('/workspace/dir/a.txt', 'four\n', append=True))
    chunk = run(store.read_file('/workspace/dir/a.txt', start_line=2, max_lines=2))
    assert chunk.text == 'two\nthree' and chunk.first_line == 2 and chunk.total_lines == 4 and chunk.next_line == 4
    assert run(store.read_file('/workspace/dir/a.txt', start_line=4, max_lines=10)).next_line is None
    assert run(store.edit_file('/workspace/dir/a.txt', 'two', 'TWO')) == 1
    assert 'TWO' in run(store.read_file('/workspace/dir/a.txt', start_line=1, max_lines=10)).text
    assert store.mutation_epoch == 3
    assert not [p for p in (store.roots['/workspace'] / 'dir').iterdir() if p.name.startswith('.write-')]


def test_edit_requires_exactly_one_match(store):
    run(store.write_file('/workspace/a.txt', 'x x y', append=False))
    with pytest.raises(SandboxError) as many:
        run(store.edit_file('/workspace/a.txt', 'x', 'z'))
    with pytest.raises(SandboxError) as none:
        run(store.edit_file('/workspace/a.txt', 'q', 'z'))
    with pytest.raises(SandboxError) as empty:
        run(store.edit_file('/workspace/a.txt', '', 'z'))
    assert (many.value.code, many.value.detail) == ('sandbox_edit_ambiguous', '2 matches')
    assert none.value.code == 'sandbox_edit_not_found' and empty.value.code == 'sandbox_edit_empty_match'
    assert run(store.read_file('/workspace/a.txt', start_line=1, max_lines=5)).text == 'x x y'


def test_quota_binary_and_directory_errors(store):
    with pytest.raises(SandboxError) as quota:
        run(store.write_file('/workspace/big.txt', 'a' * 20_000, append=False))
    assert quota.value.code == 'sandbox_quota_exceeded'
    (store.roots['/workspace'] / 'blob.bin').write_bytes(b'\x00\x01\x02')
    with pytest.raises(SandboxError) as binary:
        run(store.read_file('/workspace/blob.bin', start_line=1, max_lines=5))
    assert binary.value.code == 'sandbox_binary_file'
    (store.roots['/workspace'] / 'd').mkdir()
    for call in (store.read_file('/workspace/d', start_line=1, max_lines=5), store.write_file('/workspace/d', 'x', append=False)):
        with pytest.raises(SandboxError) as error:
            run(call)
        assert error.value.code == 'sandbox_is_a_directory'
    with pytest.raises(SandboxError) as missing:
        run(store.read_file('/workspace/nope.txt', start_line=1, max_lines=5))
    assert missing.value.code == 'sandbox_not_found'


def test_list_and_search(store):
    run(store.write_file('/workspace/src/a.py', 'import os\nvalue = 1\n', append=False))
    run(store.write_file('/workspace/src/b.txt', 'value = 2\n', append=False))
    assert [e.path for e in run(store.list_files('/', limit=10))] == ['/workspace', '/outputs']
    listed = run(store.list_files('/workspace/src', limit=10))
    assert [(e.path, e.kind) for e in listed] == [('/workspace/src/a.py', 'file'), ('/workspace/src/b.txt', 'file')]
    hits = run(store.search_files('value', '/workspace', glob='*.py', regex=False, limit=10))
    assert [(h.path, h.line) for h in hits] == [('/workspace/src/a.py', 2)]
    assert run(store.search_files(r'value = \d', '/workspace', glob='*', regex=True, limit=1)).__len__() == 1
    with pytest.raises(SandboxError) as bad:
        run(store.search_files('(', '/workspace', glob='*', regex=True, limit=5))
    assert bad.value.code == 'sandbox_pattern_invalid'


def test_outputs_are_collected_without_host_paths(store):
    run(store.write_file('/outputs/report.md', 'done', append=False))
    assert store.collect_outputs() == [('/outputs/report.md', 4)]


# ------------------------------------------------------------------ output sink

def test_sink_keeps_head_and_tail():
    async def feed():
        reader = asyncio.StreamReader()
        reader.feed_data(b'H' * 500 + b'M' * 5000 + b'T' * 500)
        reader.feed_eof()
        sink = Sink(1000)
        await sink.drain(reader)
        return sink
    sink = run(feed())
    text = sink.text()
    assert sink.truncated and text.startswith('H') and text.endswith('T') and '已省略' in text and len(text) < 1100


# ------------------------------------------------------------------ local executor and manager

def test_local_session_runs_commands_with_a_clean_environment(tmp_path, monkeypatch):
    monkeypatch.setenv('SERVER_SECRET', 'leak')
    manager = SandboxManager(local_settings(tmp_path))
    session = manager.session('t1', 's1')
    result = run(session.exec('echo hi; echo err >&2; echo $SERVER_SECRET; exit 3', cwd='/workspace', timeout_seconds=5))
    assert result.exit_code == 3 and 'hi' in result.stdout and 'leak' not in result.stdout and result.stderr.strip() == 'err'
    assert not result.timed_out


def test_local_timeout_kills_the_whole_process_group(tmp_path):
    session = SandboxManager(local_settings(tmp_path)).session('t1', 's1')
    marker = tmp_path / 'sbx' / 't1' / 's1' / 'workspace' / 'late.txt'
    result = run(session.exec(f'(sleep 2; echo late > {marker}) & sleep 30', cwd='/workspace', timeout_seconds=1))
    assert result.timed_out and result.exit_code is None
    run(asyncio.sleep(2.5))
    assert not marker.exists()


def test_exec_validation_and_timeout_ceiling(tmp_path):
    manager = SandboxManager(local_settings(tmp_path, exec_timeout_max_seconds=1))
    session = manager.session('t1', 's1')
    for bad in ('', '   '):
        with pytest.raises(SandboxError):
            run(session.exec(bad, cwd='/workspace', timeout_seconds=1))
    with pytest.raises(SandboxError):
        run(session.exec('true', cwd='/etc', timeout_seconds=1))
    assert run(session.exec('sleep 5', cwd='/workspace', timeout_seconds=100)).timed_out  # clamped to the deployment ceiling


def test_sessions_of_different_tenants_do_not_share_files(tmp_path):
    manager = SandboxManager(local_settings(tmp_path))
    a, b = manager.session('tenant-a', 's'), manager.session('tenant-b', 's')
    run(a.write_file('/workspace/x.txt', 'secret', append=False))
    with pytest.raises(SandboxError):
        run(b.read_file('/workspace/x.txt', start_line=1, max_lines=5))


@pytest.mark.parametrize('bad', ['../x', 'a/b', '', 'a' * 65, 'a b'])
def test_tenant_and_session_ids_cannot_escape_the_root(tmp_path, bad):
    with pytest.raises(SandboxError) as error:
        SandboxManager(local_settings(tmp_path)).session(bad, 's')
    assert error.value.code == 'sandbox_session_invalid'


# ------------------------------------------------------------------ docker backend against a CLI stand-in

FAKE_DOCKER = textwrap.dedent('''\
    #!%(python)s
    import json, os, subprocess, sys
    state, log = %(state)r, %(log)r
    args = sys.argv[1:]
    with open(log, 'a') as f:
        f.write(json.dumps(args) + '\\n')
    names = json.load(open(state)) if os.path.exists(state) else []
    cmd = args[0]
    if cmd == 'inspect':
        if args[-1] in names:
            print('true'); sys.exit(0)
        sys.exit(1)
    if cmd == 'run':
        names.append(args[args.index('--name') + 1]); json.dump(names, open(state, 'w')); print('id'); sys.exit(0)
    if cmd == 'rm':
        names = [n for n in names if n != args[-1]]; json.dump(names, open(state, 'w')); sys.exit(0)
    if cmd == 'ps':
        print('\\n'.join(names)); sys.exit(0)
    if cmd == 'exec':
        rest = args[1:]
        if rest[0] == '-w':
            rest = rest[2:]
        rest = rest[1:]  # container name
        sys.exit(subprocess.call(rest))
    sys.exit(2)
''')


@pytest.fixture
def fake_docker(tmp_path):
    script = tmp_path / 'docker'
    state, log = tmp_path / 'state.json', tmp_path / 'calls.log'
    script.write_text(FAKE_DOCKER % {'python': sys.executable, 'state': str(state), 'log': str(log)})
    script.chmod(script.stat().st_mode | stat.S_IEXEC)

    def calls():
        return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
    return str(script), calls


def docker_settings(tmp_path, **overrides):
    return SandboxSettings(enabled=True, backend='docker', workspace_root=str(tmp_path / 'sbx'), **overrides)


def test_container_is_started_with_every_isolation_flag(tmp_path, fake_docker):
    binary, calls = fake_docker
    settings = docker_settings(tmp_path, memory_mb=256, pids=64, cpus=0.5)
    manager = SandboxManager(settings, docker=DockerBackend(settings, binary=binary))
    run(manager.session('t1', 's1').exec('echo hi', cwd='/workspace', timeout_seconds=5))
    started = next(c for c in calls() if c[0] == 'run')
    joined = ' '.join(started)
    for flag in ('--network none', '--read-only', '--cap-drop ALL', '--security-opt no-new-privileges', '--pids-limit 64',
                 '--memory 256m', '--memory-swap 256m', '--cpus 0.5', '--pull never', '--init'):
        assert flag in joined, flag
    assert '--user' in started and started[started.index('--user') + 1].split(':')[0] != '0'
    assert started[started.index('--name') + 1] == container_name('t1', 's1')
    assert all(not value.startswith(('/home', '/etc', '/root')) for value in started if ':' in value and value.startswith('/'))
    mounts = [started[i + 1] for i, value in enumerate(started) if value == '-v']
    assert len(mounts) == 2 and mounts[0].endswith(':/workspace') and mounts[1].endswith(':/outputs')


def test_container_starts_once_for_concurrent_commands(tmp_path, fake_docker):
    binary, calls = fake_docker
    settings = docker_settings(tmp_path)
    manager = SandboxManager(settings, docker=DockerBackend(settings, binary=binary))
    session = manager.session('t1', 's1')

    async def go():
        return await asyncio.gather(*(session.exec(f'echo {i}', cwd='/workspace', timeout_seconds=5) for i in range(4)))
    results = run(go())
    assert sorted(r.stdout.strip() for r in results) == ['0', '1', '2', '3']
    assert sum(1 for c in calls() if c[0] == 'run') == 1


def test_docker_exec_wraps_the_command_in_timeout_and_maps_expiry(tmp_path, fake_docker):
    binary, calls = fake_docker
    settings = docker_settings(tmp_path)
    manager = SandboxManager(settings, docker=DockerBackend(settings, binary=binary))
    session = manager.session('t1', 's1')
    ok = run(session.exec('exit 7', cwd='/workspace', timeout_seconds=5))
    assert ok.exit_code == 7 and not ok.timed_out
    slow = run(session.exec('sleep 30', cwd='/workspace', timeout_seconds=1))
    assert slow.timed_out and slow.exit_code is None
    sent = next(c for c in calls() if c[0] == 'exec')
    assert sent[1:3] == ['-w', '/workspace'] and 'timeout' in sent and sent[sent.index('timeout') + 1] == '-k'
    assert sent[-3] == '-c' and sent[-1].startswith('nexus-exec-')


def test_reap_removes_idle_and_unknown_containers_only(tmp_path, fake_docker):
    binary, calls = fake_docker
    settings = docker_settings(tmp_path, idle_seconds=30)
    manager = SandboxManager(settings, docker=DockerBackend(settings, binary=binary))
    run(manager.session('t1', 's1').exec('true', cwd='/workspace', timeout_seconds=5))
    run(manager.session('t2', 's2').exec('true', cwd='/workspace', timeout_seconds=5))
    manager._last_used['t2/s2'] -= 100  # idle
    orphan = container_name('ghost', 'x')
    run(manager.docker.ensure(orphan, tmp_path / 'g1', tmp_path / 'g2'))  # a container no lease knows
    removed = run(manager.reap())
    assert sorted(removed) == sorted([container_name('t2', 's2'), orphan])
    assert run(manager.docker.list_managed()) == [container_name('t1', 's1')]


def test_local_backend_has_no_docker_to_reap(tmp_path):
    assert run(SandboxManager(local_settings(tmp_path)).reap()) == []


# ------------------------------------------------------------------ acceptance bookkeeping

def test_acceptance_refuses_the_local_backend(tmp_path):
    with pytest.raises(SandboxError) as error:
        run(acceptance.run(local_settings(tmp_path)))
    assert error.value.code == 'sandbox_acceptance_requires_isolating_backend'


def test_a_report_is_valid_only_for_its_fingerprint(tmp_path):
    settings = docker_settings(tmp_path)
    assert acceptance.passed(settings) is False
    settings.root.mkdir(parents=True)
    report = {'passed': True, 'fingerprint': acceptance.fingerprint(settings), 'items': []}
    acceptance.report_path(settings).write_text(json.dumps(report))
    assert acceptance.passed(settings) is True
    assert acceptance.passed(docker_settings(tmp_path, image='other:1')) is False
    assert acceptance.passed(docker_settings(tmp_path, memory_mb=1024)) is False
    report['passed'] = False
    acceptance.report_path(settings).write_text(json.dumps(report))
    assert acceptance.passed(settings) is False
    acceptance.report_path(settings).write_text('not json')
    assert acceptance.passed(settings) is False


def test_a_failing_or_crashing_probe_becomes_a_failed_item():
    async def boom():
        raise RuntimeError('broken')

    async def refused():
        raise SandboxError('sandbox_backend_unavailable', 'no daemon')
    assert run(acceptance._guard('x', boom)).ok is False
    item = run(acceptance._guard('y', refused))
    assert item.ok is False and 'sandbox_backend_unavailable' in item.detail


# ------------------------------------------------------------------ bwrap backend (argument list only; the jail is verified by the acceptance)

def bwrap_settings(tmp_path, **overrides):
    return SandboxSettings(enabled=True, backend='bwrap', workspace_root=str(tmp_path / 'sbx'), **overrides)


def test_bwrap_jail_has_every_isolation_flag(tmp_path):
    backend = BwrapBackend(bwrap_settings(tmp_path))
    args = backend.jail_arguments(tmp_path / 'w', tmp_path / 'o', '/workspace', 'echo hi')
    for flag in ('--die-with-parent', '--new-session', '--unshare-all', '--clearenv', '--proc', '--dev'):
        assert flag in args, flag
    assert args[args.index('--cap-drop') + 1] == 'ALL'
    assert '--share-net' not in args  # network = none keeps the network namespace unshared
    assert args[args.index('--remount-ro') + 1] == '/'
    assert args[-4:] == ['--', '/bin/sh', '-c', 'echo hi']
    binds = [(args[i + 1], args[i + 2]) for i, value in enumerate(args) if value == '--bind']
    assert [dst for _, dst in binds] == ['/workspace', '/outputs']  # the only writable host directories
    assert all(not src.startswith(('/home', '/root', '/etc')) for src, _ in binds)
    assert not any(value in args for value in ('--setenv-host', '--bind-try'))


def test_bwrap_opens_the_network_only_by_configuration(tmp_path):
    backend = BwrapBackend(bwrap_settings(tmp_path, network='bridge'))
    assert '--share-net' in backend.jail_arguments(tmp_path / 'w', tmp_path / 'o', '/workspace', 'true')


def test_bwrap_limits_wrap_the_jail_without_a_shell_injection_path(tmp_path):
    backend = BwrapBackend(bwrap_settings(tmp_path, memory_mb=256, workspace_quota_mb=10))
    inner = backend.jail_arguments(tmp_path / 'w', tmp_path / 'o', '/workspace', "echo '$(id)'; x")
    wrapped = backend.limited(inner)
    assert wrapped[:2] == ['/bin/sh', '-c'] and 'ulimit -v 262144' in wrapped[2] and 'ulimit -f 20480' in wrapped[2]
    assert wrapped[3:] == ['nexus-bwrap', *inner]  # the command is an argument, never part of the limit script
    assert "echo '$(id)'" not in wrapped[2]


def test_bwrap_manager_builds_an_executor_without_docker(tmp_path):
    manager = SandboxManager(bwrap_settings(tmp_path))
    session = manager.session('t1', 's1')
    assert manager.docker is None and isinstance(session.executor, BwrapExecutor)
    assert run(manager.reap()) == []


def test_bwrap_reports_a_missing_binary(tmp_path):
    settings = bwrap_settings(tmp_path)
    executor = BwrapExecutor(BwrapBackend(settings, binary='/nonexistent/bwrap'), tmp_path / 'w', tmp_path / 'o')
    with pytest.raises(SandboxError) as caught:
        run(executor.run('true', cwd='/workspace', timeout_seconds=5, output_limit=100))
    assert caught.value.code == 'sandbox_backend_unavailable'
