"""Isolation acceptance (architecture 2.9, openspec 2026-11-07-tool-expansion 3.6).

Every item is a real probe run inside the sandbox, not a configuration check. The report is stored in
`<workspace_root>/acceptance.json` together with a fingerprint of the backend, image and limits, so a change
of any of them invalidates the result. Only an isolating backend can pass: the `local` backend is refused
before any probe runs, because several probes (memory, process count) are hostile by design.

The probes assume the image offers `sh` and `python3`; an image without them fails the affected items with
a clear detail instead of being skipped.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

from nexus_core.sandbox import SandboxError
from .manager import SandboxManager
from .settings import SandboxSettings

REPORT_FILE = 'acceptance.json'


@dataclass(frozen=True)
class Item:
    name: str
    ok: bool
    detail: str = ''


def fingerprint(settings: SandboxSettings) -> str:
    """Hash of everything that changes what the sandbox can do; a report is valid only for its fingerprint."""
    material = [settings.backend, settings.image, settings.cpus, settings.memory_mb, settings.pids, settings.network,
                settings.workspace_quota_mb]
    return hashlib.sha256(json.dumps(material).encode()).hexdigest()[:32]


def report_path(settings: SandboxSettings) -> Path:
    return settings.root / REPORT_FILE


def passed(settings: SandboxSettings) -> bool:
    """Whether a stored report passed for exactly the current backend, image and limits."""
    try:
        report = json.loads(report_path(settings).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return False
    return bool(report.get('passed')) and report.get('fingerprint') == fingerprint(settings)


async def _guard(name: str, probe) -> Item:
    try:
        ok, detail = await asyncio.wait_for(probe(), 180)
    except SandboxError as error:
        return Item(name, False, f'{error.code} {error.detail}'.strip())
    except Exception as error:  # a broken probe is a failed item, never a crash of the whole check
        return Item(name, False, f'{type(error).__name__}: {str(error)[:200]}')
    return Item(name, bool(ok), detail)


async def run(settings: SandboxSettings, *, manager: SandboxManager | None = None) -> dict:
    """Run every probe and store the report. Raises `sandbox_acceptance_requires_isolating_backend` for `local`."""
    if settings.backend != 'docker':
        raise SandboxError('sandbox_acceptance_requires_isolating_backend')
    manager = manager or SandboxManager(settings)
    tag = uuid.uuid4().hex[:12]
    a = manager.session(f'accept-{tag}-a', 'probe', default_timeout=10, output_limit=2000)
    b = manager.session(f'accept-{tag}-b', 'probe', default_timeout=10, output_limit=2000)
    marker = f'NEXUS_PROBE_{tag}'
    os.environ[marker] = 'server-secret'
    limit = 2000

    async def sh(session, command, timeout=10):
        return await session.exec(command, cwd='/workspace', timeout_seconds=timeout)

    async def connectivity():
        await a.write_file('/workspace/probe.txt', 'ping', append=False)
        read = await a.read_file('/workspace/probe.txt', start_line=1, max_lines=5)
        seen = await sh(a, 'cat /workspace/probe.txt')
        await sh(a, 'rm /workspace/probe.txt')
        return read.text == 'ping' and seen.stdout.strip() == 'ping', 'write, read, command and delete'

    async def user():
        result = await sh(a, 'id -u; touch /etc/nexus-probe; echo $?')
        lines = result.stdout.split()
        return bool(lines) and lines[0] != '0' and lines[-1] != '0', 'runs as a non-root user and cannot write the root file system'

    async def network():
        if settings.network != 'none':
            return True, 'network is open by configuration; the guard rules and approvals apply instead'
        result = await sh(a, 'python3 -c "import socket; socket.create_connection((\'1.1.1.1\', 53), 3)"', 15)
        dns = await sh(a, 'python3 -c "import socket; socket.gethostbyname(\'example.com\')"', 15)
        return result.exit_code not in (0, None) and dns.exit_code not in (0, None), 'no TCP connection and no DNS resolution'

    async def time_limit():
        started = time.monotonic()
        result = await sh(a, 'sleep 60', 2)
        return result.timed_out and time.monotonic() - started < 15, 'a command past its timeout is killed'

    async def output_limit():
        result = await sh(a, 'yes x | head -c 3000000')
        return result.stdout_truncated and len(result.stdout) < limit * 3, 'huge output is cut to the limit'

    async def memory_limit():
        size = settings.memory_mb * 2 * 1024 * 1024
        result = await sh(a, f'python3 -c "b = bytearray({size}); print(len(b))"', 30)
        return result.exit_code not in (0, None) and str(size) not in result.stdout, 'allocating twice the limit is refused or killed'

    async def process_limit():
        code = ('import os,time\\nn=0\\nfor _ in range(%d):\\n try:\\n  if os.fork()==0:\\n   time.sleep(8);os._exit(0)\\n  n+=1\\n'
                ' except OSError:\\n  break\\nprint(n)') % (settings.pids * 2)
        result = await sh(a, f'python3 -c "$(printf \'{code}\')"', 30)
        try:
            forked = int(result.stdout.split()[-1])
        except (ValueError, IndexError):
            return False, f'no count reported: {result.stderr[:100]}'
        return forked < settings.pids, f'{forked} processes created, limit {settings.pids}'

    async def tenant_isolation():
        await a.write_file('/workspace/secret.txt', 'tenant-a', append=False)
        try:
            await b.read_file('/workspace/secret.txt', start_line=1, max_lines=5)
            return False, 'the other tenant could read the file'
        except SandboxError:
            pass
        other = await sh(b, 'cat /workspace/secret.txt')
        return 'tenant-a' not in other.stdout, 'a second tenant cannot see the first one\'s files'

    async def path_escape():
        await sh(a, 'ln -s /etc/passwd /workspace/link')
        for path in ('/workspace/../etc/passwd', '/etc/passwd', '/workspace/link'):
            try:
                await a.read_file(path, start_line=1, max_lines=5)
                return False, f'{path} was readable'
            except SandboxError as error:
                if error.code not in ('sandbox_path_invalid', 'sandbox_not_found'):
                    return False, f'{path}: {error.code}'
        return True, 'traversal, absolute paths and symbolic links out of the root are refused'

    async def environment():
        result = await sh(a, 'env')
        return marker not in result.stdout and 'server-secret' not in result.stdout, 'the server environment is not inherited'

    async def cancellation():
        task = asyncio.ensure_future(sh(a, 'echo $$ > /workspace/.pid; sleep 60', 60))
        await asyncio.sleep(3)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await asyncio.sleep(1)
        result = await sh(a, 'kill -0 "$(cat /workspace/.pid)" 2>/dev/null && echo alive || echo gone')
        return 'gone' in result.stdout, 'a cancelled command does not keep running in the container'

    async def cleanup_and_residue():
        docker = manager.docker
        await manager.release(f'accept-{tag}-a', 'probe')
        names = await docker.list_managed()
        from .backends.docker import container_name
        gone = container_name(f'accept-{tag}-a', 'probe') not in names
        # A container whose lease this process forgot (the crash case) must be found and removed by `reap`.
        manager._last_used.pop(f'accept-{tag}-b/probe', None)
        removed = await manager.reap()
        leftover = container_name(f'accept-{tag}-b', 'probe') in await docker.list_managed()
        return gone and not leftover, f'released container removed; {len(removed)} orphan(s) reclaimed'

    items = []
    try:
        for name, probe in (('connectivity', connectivity), ('user', user), ('network', network), ('time_limit', time_limit),
                            ('output_limit', output_limit), ('memory_limit', memory_limit), ('process_limit', process_limit),
                            ('tenant_isolation', tenant_isolation), ('path_escape', path_escape),
                            ('environment', environment), ('cancellation', cancellation), ('cleanup_and_residue', cleanup_and_residue)):
            items.append(await _guard(name, probe))
    finally:
        os.environ.pop(marker, None)
        for suffix in ('a', 'b'):
            try:
                await manager.release(f'accept-{tag}-{suffix}', 'probe')
            except Exception:
                pass
    report = {'passed': all(item.ok for item in items), 'fingerprint': fingerprint(settings), 'backend': settings.backend,
              'image': settings.image, 'checked_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
              'items': [asdict(item) for item in items]}
    settings.root.mkdir(parents=True, exist_ok=True)
    report_path(settings).write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
    return report
