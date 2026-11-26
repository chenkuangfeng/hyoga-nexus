"""Docker backend: one long-lived container per (tenant, session), commands run with `docker exec`.

Isolation comes from the container, not from this code: non-root user, no capabilities, no new privileges,
read-only root file system, no network unless the deployment opens it, and CPU, memory and process limits.
Only the workspace and outputs directories of this session are mounted; nothing of the host is exposed and
the server's environment is never passed on. The `docker` binary is driven through its CLI so that no SDK
dependency is needed. This module is verified against a recording stand-in for the CLI in the unit tests;
the real daemon is covered by the isolation acceptance (`nexus_sandbox.acceptance`).
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import signal
import time
import uuid
from pathlib import Path

from nexus_core.sandbox import ExecResult, SandboxError
from ...settings import SandboxSettings
from ..output import Sink, feed_stdin

LABEL = 'nexus.sandbox'
#: Label naming the profile that owns a container, so each profile's manager reclaims only its own.
PROFILE_LABEL = 'nexus.sandbox.profile'
#: `timeout` exits with 124 on expiry (137 when it had to send SIGKILL).
_TIMEOUT_CODES = (124, 137)
_GRACE_SECONDS = 2


def container_name(tenant_id: str, session_id: str, profile: str = 'default', configuration_id: str = '') -> str:
    """Stable, collision-resistant container name for a (tenant, session, profile) triple.

    The profile joins the hash only when it is not ``default``, so containers created before profiles existed keep
    their names. Two profiles of one session (an agent version that changed its profile) never share a container.
    """
    material = f'{tenant_id}\0{session_id}' + ('' if profile == 'default' else f'\0{profile}')
    if configuration_id:
        material += f'\0{configuration_id}'
    return 'nexus-sbx-' + hashlib.sha256(material.encode()).hexdigest()[:20]


async def run_cli(binary: str, *args: str, timeout: float = 60) -> tuple[int, str, str]:
    """Run one short docker command and return (exit code, stdout, stderr)."""
    process = await asyncio.create_subprocess_exec(
        binary, *args, stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        out, err = await asyncio.wait_for(process.communicate(), timeout)
    except (asyncio.TimeoutError, asyncio.CancelledError) as error:
        if process.returncode is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
        await process.wait()
        if isinstance(error, asyncio.CancelledError):
            raise
        raise SandboxError('sandbox_backend_timeout') from None
    return process.returncode, out.decode('utf-8', 'replace'), err.decode('utf-8', 'replace')


class DockerBackend:
    """Creates and drives session containers. One instance serves the whole process."""

    def __init__(self, settings: SandboxSettings, *, binary: str = 'docker', lifetime: int | None = None):
        self.settings, self.binary = settings, binary
        self.lifetime = lifetime
        self._locks: dict[str, asyncio.Lock] = {}

    # ------------------------------------------------------------------ lifecycle

    def run_arguments(self, name: str, workspace: Path, outputs: Path, skills: Path | None = None,
                      envs: Path | None = None) -> list[str]:
        """The `docker run` arguments of a session container. Pure, so the isolation flags are testable."""
        s = self.settings
        uid = os.getuid() if os.getuid() != 0 else 65534
        gid = os.getgid() if os.getuid() != 0 else 65534
        passthrough = [flag for key in s.env_passthrough if key in os.environ for flag in ('-e', f'{key}={os.environ[key]}')]
        return ['run', '-d', '--name', name, '--label', f'{LABEL}=1', '--label', f'{PROFILE_LABEL}={s.profile}',
                *(['--rm'] if self.lifetime is not None else []),
                '--pull', 'never', '--init',
                '--network', s.network, '--read-only', '--tmpfs', f'/tmp:rw,size={s.tmpfs_mb}m',
                '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
                '--cpus', str(s.cpus), '--memory', f'{s.memory_mb}m', '--memory-swap', f'{s.memory_mb}m',
                '--pids-limit', str(s.pids), '--user', f'{uid}:{gid}',
                '-v', f'{workspace.resolve()}:/workspace', '-v', f'{outputs.resolve()}:/outputs',
                *(['-v', f'{skills.resolve()}:/skills:ro'] if skills is not None else []),
                *(['-v', f'{envs.resolve()}:/skill_envs:ro'] if envs is not None else []),
                '-e', 'HOME=/workspace', '-e', 'LANG=C.UTF-8', *passthrough, '-w', '/workspace',
                s.image, 'sleep', str(self.lifetime or 2147483647)]

    async def ensure(self, name: str, workspace: Path, outputs: Path, skills: Path | None = None,
                     envs: Path | None = None) -> None:
        """Start the container when it is not running. Concurrent callers for one name share one start."""
        lock = self._locks.setdefault(name, asyncio.Lock())
        async with lock:
            code, out, _ = await run_cli(self.binary, 'inspect', '-f', '{{.State.Running}}', name)
            if code == 0 and out.strip() == 'true':
                return
            if code == 0:
                await run_cli(self.binary, 'rm', '-f', name)  # exists but stopped (for example after a daemon restart)
            if os.getuid() == 0:
                for directory in (workspace, outputs):
                    directory.chmod(0o777)  # the container runs as nobody; the server is root
            code, _, err = await run_cli(self.binary, *self.run_arguments(name, workspace, outputs, skills, envs), timeout=120)
            if code != 0:
                raise SandboxError('sandbox_backend_unavailable', err.strip()[:300])

    async def remove(self, name: str) -> None:
        code, _, error = await run_cli(self.binary, 'rm', '-f', name)
        if self.lifetime is not None and code != 0 and 'No such container' not in error:
            raise SandboxError('sandbox_remote_cleanup_unconfirmed')

    async def list_managed(self) -> list[str]:
        """Names of the containers this profile created (label match), for idle and orphan reclamation."""
        code, out, _ = await run_cli(self.binary, 'ps', '-a', '--filter', f'label={LABEL}=1',
                                     '--filter', f'label={PROFILE_LABEL}={self.settings.profile}', '--format', '{{.Names}}')
        return [line for line in out.splitlines() if line] if code == 0 else []

    # ------------------------------------------------------------------ commands

    def exec_arguments(self, name: str, command: str, cwd: str, timeout_seconds: float, token: str,
                       env: dict[str, str] | None = None, stdin: bool = False) -> list[str]:
        """`docker exec` arguments. `timeout` leads its own process group, so expiry ends the whole command tree;
        `token` becomes `$0` of the shell so a cancelled command can be found again by its command line."""
        return ['exec', *(['-i'] if stdin else []), '-w', cwd, *[flag for key, value in (env or {}).items() for flag in ('-e', f'{key}={value}')],
                name, 'timeout', '-k', str(_GRACE_SECONDS), str(max(1, int(timeout_seconds))),
                'sh', '-c', command, token]

    async def kill_command(self, name: str, token: str) -> None:
        """Kill the process group of the command tagged `token` (used on cancellation; best effort)."""
        script = ('for p in /proc/[0-9]*; do [ "${p#/proc/}" = "$$" ] && continue; '
                  f'if tr "\\0" " " < "$p/cmdline" 2>/dev/null | grep -q "{token}"; then kill -9 -- "-${{p#/proc/}}" 2>/dev/null; fi; done; true')
        try:
            await run_cli(self.binary, 'exec', name, 'sh', '-c', script, timeout=10)
        except SandboxError:
            pass


class DockerExecutor:
    """`CommandExecutorPort` for one session container."""

    #: Projected skills appear read-only at `/skills`; `/outputs` is the real container path.
    skills_mount = '/skills'
    #: Built dependency environments appear read-only at `/skill_envs/<name>`.
    envs_mount = '/skill_envs'
    outputs_path = '/outputs'

    def __init__(self, backend: DockerBackend, name: str, workspace: Path, outputs: Path, skills: Path | None = None,
                 envs: Path | None = None):
        self.backend, self.name, self.workspace, self.outputs, self.skills = backend, name, workspace, outputs, skills
        self.envs = envs

    async def run(self, command: str, *, cwd: str, timeout_seconds: float, output_limit: int,
                  env: dict[str, str] | None = None, stdin: str | None = None) -> ExecResult:
        from ... import paths
        paths.split(cwd)  # only /workspace and /outputs are valid working directories
        await self.backend.ensure(self.name, self.workspace, self.outputs, self.skills, self.envs)
        started = time.monotonic()
        token = 'nexus-exec-' + uuid.uuid4().hex
        process = await asyncio.create_subprocess_exec(
            self.backend.binary, *self.backend.exec_arguments(self.name, command, cwd, timeout_seconds, token, env, stdin is not None),
            stdin=asyncio.subprocess.PIPE if stdin is not None else asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            start_new_session=True)
        out, err = Sink(output_limit), Sink(output_limit)

        def kill_client() -> None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

        try:
            # In-container `timeout` ends the command; this outer bound only guards a hung docker client.
            await asyncio.wait_for(asyncio.gather(out.drain(process.stdout), err.drain(process.stderr), process.wait(),
                                                  feed_stdin(process, stdin)), timeout_seconds + _GRACE_SECONDS + 5)
        except asyncio.TimeoutError:
            kill_client()
            await process.wait()
            await self.backend.kill_command(self.name, token)
            return ExecResult(None, True, out.text(), err.text(), out.truncated, err.truncated,
                              int((time.monotonic() - started) * 1000))
        except BaseException:
            # Cancelled: dropping the docker client does not stop the command inside the container.
            kill_client()
            await asyncio.shield(self.backend.kill_command(self.name, token))
            raise
        elapsed = time.monotonic() - started
        timed_out = process.returncode in _TIMEOUT_CODES and elapsed >= max(1, int(timeout_seconds)) - 0.5
        return ExecResult(None if timed_out else process.returncode, timed_out, out.text(), err.text(),
                          out.truncated, err.truncated, int(elapsed * 1000))

    async def close(self) -> None:
        await self.backend.remove(self.name)
