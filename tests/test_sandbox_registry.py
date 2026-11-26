"""Cross-platform control registry: locking, UTF-8 and closed-file atomic publication."""
from dataclasses import replace
import errno
import os
import sys
from types import SimpleNamespace

import pytest

from nexus_sandbox import registry
from nexus_sandbox.settings import SandboxConfig


@pytest.fixture
def windows_lock(monkeypatch):
    """Exercise Windows dispatch on Linux without replacing OS/pathlib platform detection."""
    events = []
    def locking(fd, mode, count):
        assert os.lseek(fd, 0, os.SEEK_CUR) == 0
        assert count == 1
        events.append((fd, mode))
    backend = SimpleNamespace(LK_NBLCK=1, LK_UNLCK=2, locking=locking)
    monkeypatch.setitem(sys.modules, 'msvcrt', backend)
    monkeypatch.setattr(registry, '_WINDOWS', True)
    def no_posix(*args, **kwargs):
        raise AssertionError('Windows registry must not enter the POSIX lock')
    monkeypatch.setattr(registry, 'mutation', no_posix)
    return backend, events


def test_windows_registry_retries_contention_and_unlocks_on_failure(tmp_path, windows_lock, monkeypatch):
    backend, events = windows_lock
    original = backend.locking
    attempts, delays = [], []
    def contended(fd, mode, count):
        if mode == backend.LK_NBLCK:
            attempts.append(fd)
            if len(attempts) == 1:
                raise OSError(errno.EACCES, 'locked by another writer')
        original(fd, mode, count)
    monkeypatch.setattr(backend, 'locking', contended)
    monkeypatch.setattr(registry.time, 'sleep', delays.append)
    with pytest.raises(RuntimeError, match='write failed'):
        with registry._registry_lock(tmp_path):
            raise RuntimeError('write failed')
    assert len(attempts) == 2 and delays == [.05]
    assert [mode for _, mode in events] == [backend.LK_NBLCK, backend.LK_UNLCK]
    with pytest.raises(OSError):
        os.fstat(events[-1][0])  # lock descriptor is closed even after an exception


def test_windows_registry_does_not_retry_storage_errors(tmp_path, windows_lock, monkeypatch):
    backend, _ = windows_lock
    def broken(*args):
        raise OSError(errno.EIO, 'storage unavailable')
    monkeypatch.setattr(backend, 'locking', broken)
    monkeypatch.setattr(registry.time, 'sleep', lambda _: pytest.fail('storage errors must not be retried'))
    with pytest.raises(OSError) as error:
        with registry._registry_lock(tmp_path):
            pytest.fail('lock was not acquired')
    assert error.value.errno == errno.EIO


def test_windows_registry_closes_temporary_before_replace_and_cleans_failures(tmp_path, windows_lock, monkeypatch):
    backend, events = windows_lock
    streams = []
    original_temp = registry.tempfile.NamedTemporaryFile
    original_replace = registry.os.replace
    def temporary(*args, **kwargs):
        stream = original_temp(*args, **kwargs)
        streams.append(stream)
        return stream
    def publish(source, target):
        assert all(stream.closed for stream in streams)
        return original_replace(source, target)
    monkeypatch.setattr(registry.tempfile, 'NamedTemporaryFile', temporary)
    monkeypatch.setattr(registry.os, 'replace', publish)
    config = replace(SandboxConfig(), workspace_root=str(tmp_path))
    values = {'type': 'docker', 'display_name': '中文沙箱', 'description': '开发环境'}
    registry.write(config, 'custom', values, 0)
    assert registry.read(tmp_path)['profiles']['custom'] == values
    assert registry.merge(config).get('custom').display_name == '中文沙箱'
    with pytest.raises(registry.RegistryConflict):
        registry.write(config, 'custom', values, 0)
    def fail_publish(source, target):
        assert all(stream.closed for stream in streams)
        raise PermissionError('target locked')
    monkeypatch.setattr(registry.os, 'replace', fail_publish)
    with pytest.raises(PermissionError):
        registry.write(config, 'custom', values | {'display_name': '修改'}, 1)
    assert registry.read(tmp_path)['revision'] == 1
    assert registry.read(tmp_path)['profiles']['custom']['display_name'] == '中文沙箱'
    assert sorted(path.name for path in tmp_path.iterdir()) == sorted([registry.FILE, '_execution_locks'])
    assert len(events) == 6 and events[-1][1] == backend.LK_UNLCK


def test_native_registry_serializes_competing_processes(tmp_path):
    """Uses real fcntl on POSIX and real msvcrt when this suite runs on Windows."""
    import subprocess
    code = '''
from dataclasses import replace
import sys
from nexus_sandbox.settings import SandboxConfig
from nexus_sandbox.registry import write, RegistryConflict
config = replace(SandboxConfig(), workspace_root=sys.argv[1])
try:
    write(config, sys.argv[2], {'type': 'docker', 'display_name': '\\u4e2d\\u6587'}, 0)
    print('saved')
except RegistryConflict:
    print('conflict')
'''
    children = [subprocess.Popen([sys.executable, '-c', code, str(tmp_path), name],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                for name in ('first', 'second')]
    try:
        results = [child.communicate(timeout=20) for child in children]
        assert all(child.returncode == 0 for child in children), results
        assert sorted(out.strip() for out, _ in results) == ['conflict', 'saved']
        data = registry.read(tmp_path)
        assert data['revision'] == 1 and len(data['profiles']) == 1
        assert next(iter(data['profiles'].values()))['display_name'] == '中文'
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
            child.wait()
