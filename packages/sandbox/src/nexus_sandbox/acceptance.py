"""Isolation acceptance (architecture 2.9, openspec 2026-11-07-tool-expansion 3.6).

Every item is a real probe run inside the sandbox, not a configuration check. The report is stored in
a `ReportStore` together with a fingerprint of the backend, image and limits, so a change of any of them
invalidates the result. The platform stores reports in its database (so an API and a worker on different hosts
agree); this package knows only the port and a file implementation, which is also the fallback for a report made
before the database table existed. Only an isolating backend can pass: the `local` backend is refused
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
from typing import Protocol

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
                settings.workspace_quota_mb, settings.tmpfs_mb, list(settings.env_passthrough)]
    if settings.backend == 'docker':
        material.append('docker-cpu-v1')
    if settings.backend in ('ssh', 'managed'):
        material.extend(['remote-v1', settings.remote_profile, settings.ssh_host, settings.ssh_port,
                         settings.ssh_user, settings.ssh_known_hosts, settings.ssh_identity_file,
                         settings.trusted_ssh, settings.endpoint, settings.token_file,
                         settings.exec_timeout_max_seconds, settings.skill_timeout_max_seconds])
    return hashlib.sha256(json.dumps(material).encode()).hexdigest()[:32]


def report_path(settings: SandboxSettings) -> Path:
    """Where the report of this profile is stored: `acceptance.json` for the legacy `default` profile (so reports
    made before profiles still count), `acceptance-<profile>.json` for the others."""
    if settings.profile == 'default':
        return settings.root / REPORT_FILE
    return settings.root / f'acceptance-{settings.profile}.json'


class ReportStore(Protocol):
    """Where acceptance reports live. `load` returns None when the store has no report for the profile."""

    def load(self, settings: SandboxSettings) -> dict | None: ...

    def save(self, settings: SandboxSettings, report: dict) -> None: ...


class FileReportStore:
    """Reports as JSON files under `workspace_root` (see `report_path`)."""

    def load(self, settings: SandboxSettings) -> dict | None:
        try:
            report = json.loads(report_path(settings).read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return None
        return report if isinstance(report, dict) else None

    def save(self, settings: SandboxSettings, report: dict) -> None:
        settings.root.mkdir(parents=True, exist_ok=True)
        report_path(settings).write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')


def valid(settings: SandboxSettings, report: dict | None) -> bool:
    """Whether `report` passed for exactly the current backend, image and limits."""
    return bool(report) and bool(report.get('passed')) and report.get('fingerprint') == fingerprint(settings)


def passed(settings: SandboxSettings, store: ReportStore | None = None) -> bool:
    """Whether a stored report passed for exactly the current backend, image and limits.

    A report in `store` decides, even a stale one (it was made after the file). Only when `store` has none does the
    file written by an earlier version count, so an upgrade does not force a new acceptance run. A store that
    cannot be read counts as not accepted.
    """
    report = None
    if store is not None:
        try:
            report = store.load(settings)
        except Exception:
            return False  # an unreadable store is "not accepted", never a reason to trust an older file
    if report is None:
        report = FileReportStore().load(settings)
    return valid(settings, report)


def _host_processes(marker_seconds: int) -> list[str]:
    """Pids on the host running `sleep <marker_seconds>`. Backends without a container (bwrap) cannot be asked
    from the inside (every command has its own PID namespace), so their probes look for a marker process here."""
    needle = f'sleep\x00{marker_seconds}'.encode()
    found = []
    for entry in Path('/proc').iterdir():
        if entry.name.isdigit():
            try:
                if needle in (entry / 'cmdline').read_bytes():
                    found.append(entry.name)
            except OSError:
                pass
    return found


def _marker_seconds() -> int:
    """A sleep length no other process is likely to use, different on every run."""
    return 3000 + (os.getpid() * 7 + int(time.time())) % 900


async def _guard(name: str, probe) -> Item:
    try:
        ok, detail = await asyncio.wait_for(probe(), 180)
    except SandboxError as error:
        return Item(name, False, f'{error.code} {error.detail}'.strip())
    except Exception as error:  # a broken probe is a failed item, never a crash of the whole check
        return Item(name, False, f'{type(error).__name__}: {str(error)[:200]}')
    return Item(name, bool(ok), detail)


async def run(settings: SandboxSettings, *, manager: SandboxManager | None = None,
              store: ReportStore | None = None) -> dict:
    """Run every probe and store the report (in `store` when given, and always as a file copy for operators). Raises `sandbox_acceptance_requires_isolating_backend` for `local`."""
    if settings.backend not in ('docker', 'bwrap', 'ssh', 'managed'):
        raise SandboxError('sandbox_acceptance_requires_isolating_backend')
    if settings.backend == 'ssh' and not settings.trusted_ssh:
        raise SandboxError('sandbox_ssh_not_allowed')
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
        deleted = await sh(a, 'rm /workspace/probe.txt && python3 -c "print(1234)"')
        return (read.text == 'ping' and seen.exit_code == 0 and seen.stdout.strip() == 'ping'
                and deleted.exit_code == 0 and deleted.stdout.strip() == '1234'), 'write, read, command and delete'

    async def user():
        result = await sh(a, 'id -u; touch /etc/nexus-probe; echo $?')
        lines = result.stdout.split()
        return (len(lines) == 2 and all(line.isdigit() for line in lines) and lines[0] != '0'
                and lines[1] != '0'), 'runs as a non-root user and cannot write the root file system'

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
        if settings.backend == 'bwrap':
            return await processes_bounded_by_teardown()
        code = ('import os,time\\nn=0\\nfor _ in range(%d):\\n try:\\n  if os.fork()==0:\\n   time.sleep(8);os._exit(0)\\n  n+=1\\n'
                ' except OSError:\\n  break\\nprint(n)') % (settings.pids * 2)
        result = await sh(a, f'python3 -c "$(printf \'{code}\')"', 30)
        try:
            forked = int(result.stdout.split()[-1])
        except (ValueError, IndexError):
            return False, f'no count reported: {result.stderr[:100]}'
        return forked < settings.pids, f'{forked} processes created, limit {settings.pids}'

    async def cpu_limit():
        result = await sh(a, 'cat /sys/fs/cgroup/cpu.max 2>/dev/null || '
                          '(cat /sys/fs/cgroup/cpu/cpu.cfs_quota_us; cat /sys/fs/cgroup/cpu/cpu.cfs_period_us)')
        try:
            quota, period = map(int, result.stdout.split())
            return result.exit_code == 0 and period > 0 and abs(quota / period - settings.cpus) < .01, 'CPU quota'
        except ValueError:
            return False, 'kernel CPU quota not readable'

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
        return (result.exit_code == 0 and marker not in result.stdout
                and 'server-secret' not in result.stdout), 'the server environment is not inherited'

    async def cancellation():
        if settings.backend == 'managed':
            await a.write_file('/workspace/cancel-state', 'waiting\n', append=False)
            task = asyncio.create_task(sh(a, 'echo started > cancel-state; sleep 20; echo finished > cancel-state', 22))
            try:
                for _ in range(180):
                    started = (await a.read_file('/workspace/cancel-state', start_line=1, max_lines=1)).text == 'started'
                    if started or task.done():
                        break
                    await asyncio.sleep(.1)
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            return started and a.executor.last_cancel_confirmed, 'gateway confirmed cancellation and teardown'
        if manager.docker is None:
            return await cancelled_jail_is_gone()
        task = asyncio.ensure_future(sh(a, 'echo $$ > /workspace/.pid; sleep 60', 60))
        await asyncio.sleep(3)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await asyncio.sleep(1)
        result = await sh(a, 'kill -0 "$(cat /workspace/.pid)" 2>/dev/null && echo alive || echo gone')
        return 'gone' in result.stdout, 'a cancelled command does not keep running in the container'

    async def cleanup_and_residue():
        if manager.docker is None:
            return await jail_leaves_nothing()
        docker = manager.docker
        await manager.release(f'accept-{tag}-a', 'probe')
        names = await docker.list_managed()
        from .backends.docker import container_name
        gone = container_name(f'accept-{tag}-a', 'probe', settings.profile) not in names
        # A container whose lease this process forgot (the crash case) must be found and removed by `reap`.
        manager._last_used.pop(f'accept-{tag}-b/probe', None)
        orphan = container_name(f'accept-{tag}-b', 'probe', settings.profile)
        removed = await manager.reap(only_names={orphan})
        leftover = orphan in await docker.list_managed()
        return gone and not leftover, f'released container removed; {len(removed)} orphan(s) reclaimed'

    async def jail_leaves_nothing():
        """Backends without a long-lived container (bwrap): a process a command left in the background must end with
        its jail. The marker is a sleep length no other process uses; the host's process table is searched for it."""
        seconds = _marker_seconds()
        await sh(a, f'sleep {seconds} & echo started')
        await asyncio.sleep(1)
        alive = _host_processes(seconds)
        return not alive, ('no container to remove: the jail ends with its command and takes background processes along'
                           if not alive else f'{len(alive)} background process(es) outlived the jail')

    async def cancelled_jail_is_gone():
        """A cancelled command must not leave its jail running (the in-container check of the docker variant cannot
        work here: a later command is a different PID namespace)."""
        seconds = _marker_seconds()
        task = asyncio.ensure_future(sh(a, f'sleep {seconds}', 60))
        await asyncio.sleep(3)
        started = bool(_host_processes(seconds))
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await asyncio.sleep(1)
        alive = _host_processes(seconds)
        return started and not alive, 'a cancelled command does not keep running in the jail'

    async def processes_bounded_by_teardown():
        """bwrap has no process-count limit (a real one needs a cgroup). What it does guarantee, and what is checked,
        is that the processes a command forks end with its jail: after the command they are all gone."""
        seconds = _marker_seconds()
        code = ('import os,time\\nn=0\\nfor _ in range(%d):\\n try:\\n  if os.fork()==0:\\n   os.execvp("sleep",["sleep","%d"])\\n  n+=1\\n'
                ' except OSError:\\n  break\\ntime.sleep(1)\\nprint(n)') % (settings.pids * 2, seconds)
        result = await sh(a, f'python3 -c "$(printf \'{code}\')"', 30)
        await asyncio.sleep(1)
        alive = _host_processes(seconds)
        try:
            forked = int(result.stdout.split()[-1])
        except (ValueError, IndexError):
            return False, f'no count reported: {result.stderr[:100]}'
        return not alive, (f'no process-count limit with bwrap; {forked} processes forked and all ended with the jail'
                           if not alive else f'{len(alive)} of {forked} forked processes outlived the jail')

    items = []
    try:
        probes = [('connectivity', connectivity), ('user', user), ('network', network), ('time_limit', time_limit),
                  ('output_limit', output_limit), ('memory_limit', memory_limit),
                  ('tenant_isolation', tenant_isolation), ('path_escape', path_escape), ('environment', environment)]
        if settings.backend != 'ssh':
            probes.extend([('process_limit', process_limit), ('cancellation', cancellation)])
        if settings.backend in ('docker', 'managed'):
            probes.append(('cpu_limit', cpu_limit))
        if settings.backend in ('docker', 'bwrap'):
            probes.append(('cleanup_and_residue', cleanup_and_residue))
        for name, probe in probes:
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
    FileReportStore().save(settings, report)
    if store is not None:
        store.save(settings, report)
    return report
