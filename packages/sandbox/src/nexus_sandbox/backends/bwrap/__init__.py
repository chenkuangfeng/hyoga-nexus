"""Bubblewrap backend: every command runs in a fresh, unprivileged Linux namespace jail (no daemon, no image).

Isolation comes from `bwrap`, not from this code. A command sees the host's system directories read-only
(`/usr` and the `/bin`, `/lib` family), a private `/proc`, `/dev` and `/tmp`, and exactly two writable
directories: the session's `/workspace` and `/outputs`. Nothing else of the host is mounted, so host paths,
other tenants' workspaces and the server's configuration do not exist inside the jail. The jail has its own
user, PID, IPC, UTS and cgroup namespaces, and its own network namespace unless the deployment opens the
network. It is created per command and disappears with it; `--die-with-parent` and the PID namespace make
sure that killing the `bwrap` process group ends every process of the command.

What bubblewrap does not give (compared to the docker backend):

- No process-count limit. `RLIMIT_NPROC` counts all processes of the server's user, so it cannot be used;
  a real limit needs a cgroup. The wall-clock timeout and the jail teardown bound a fork bomb instead.
- Memory is limited with the address-space rlimit (`ulimit -v`), which is stricter than resident memory for
  runtimes that reserve large virtual ranges.
- No CPU quota. `ulimit -t` is not used because it limits CPU seconds of one process, not the command tree.
- The interpreter and libraries are the host's: the jail is only as complete as the host's `/usr`.
- No background commands: the jail ends with the command that started it, so `sandbox_exec_async` is refused.
- The kernel is shared with the host, exactly as with a container.

The unit tests check the argument list against the real isolation flags; whether the jail works on a given
host (unprivileged user namespaces enabled) is covered by the isolation acceptance (`nexus_sandbox.acceptance`).
"""
from __future__ import annotations

import asyncio
import os
import shutil
import signal
import time
from pathlib import Path

from nexus_core.sandbox import ExecResult, SandboxError
from ...settings import SandboxSettings
from ..output import Sink, feed_stdin

#: Directories of the host's system that are mounted read-only (or recreated as symlinks when they are links).
_SYSTEM_DIRECTORIES = ('/usr', '/bin', '/sbin', '/lib', '/lib64', '/lib32')
#: Host files a command needs to resolve names, verify TLS and link dynamically. None of them holds a secret.
_ETC_FILES = ('/etc/resolv.conf', '/etc/hosts', '/etc/nsswitch.conf', '/etc/passwd', '/etc/group', '/etc/localtime',
              '/etc/ld.so.cache', '/etc/alternatives', '/etc/ssl', '/etc/pki', '/etc/ca-certificates')
#: UID and GID used inside the jail when the server itself runs as root.
_UNPRIVILEGED_ID = 65534
_PATH = '/usr/local/bin:/usr/bin:/bin'


def find_binary(binary: str = 'bwrap') -> str | None:
    """The `bwrap` executable, or None when it is not installed."""
    return shutil.which(binary)


class BwrapBackend:
    """Builds the `bwrap` command line of one command. One instance serves the whole process."""

    def __init__(self, settings: SandboxSettings, *, binary: str = 'bwrap'):
        self.settings = settings
        self.binary = binary

    def jail_arguments(self, workspace: Path, outputs: Path, cwd: str, command: str,
                       env: dict[str, str] | None = None, skills: Path | None = None,
                       envs: Path | None = None) -> list[str]:
        """The `bwrap` argument list. Pure, so every isolation flag is testable without running anything."""
        args = [self.binary, '--die-with-parent', '--new-session', '--unshare-all', '--cap-drop', 'ALL']
        if self.settings.network != 'none':
            args.append('--share-net')  # --unshare-all removed it; the deployment opened the network
        if os.getuid() == 0:
            args += ['--uid', str(_UNPRIVILEGED_ID), '--gid', str(_UNPRIVILEGED_ID)]
        for directory in _SYSTEM_DIRECTORIES:
            path = Path(directory)
            if path.is_symlink():
                args += ['--symlink', os.readlink(directory), directory]
            elif path.exists():
                args += ['--ro-bind', directory, directory]
        for name in _ETC_FILES:
            args += ['--ro-bind-try', name, name]
        args += ['--proc', '/proc', '--dev', '/dev', '--tmpfs', '/tmp',
                 '--bind', str(workspace.resolve()), '/workspace', '--bind', str(outputs.resolve()), '/outputs',
                 *(['--ro-bind', str(skills.resolve()), '/skills'] if skills is not None else []),
                 *(['--ro-bind', str(envs.resolve()), '/skill_envs'] if envs is not None else []),
                 '--remount-ro', '/',  # the root is a tmpfs: only /workspace, /outputs and /tmp stay writable
                 # No `--clearenv`: bwrap before 0.4.1 does not know it. The environment is rebuilt anyway, because
                 # the executor starts bwrap with only PATH (`run`), so the host's variables never reach the jail.
                 '--setenv', 'PATH', _PATH, '--setenv', 'HOME', '/workspace',
                 '--setenv', 'LANG', 'C.UTF-8', '--setenv', 'LC_ALL', 'C.UTF-8', '--setenv', 'TMPDIR', '/tmp',
                 *[flag for key in self.settings.env_passthrough if key in os.environ
                   for flag in ('--setenv', key, os.environ[key])],
                 *[flag for key, value in (env or {}).items() for flag in ('--setenv', key, value)],
                 '--chdir', cwd, '--', '/bin/sh', '-c', command]
        return args

    def limited(self, args: list[str]) -> list[str]:
        """Wrap `args` in a shell that applies resource limits and then replaces itself with the jail.

        `ulimit -f` counts 512-byte blocks and bounds the size of one file; core dumps are disabled.
        """
        s = self.settings
        script = (f'ulimit -c 0; ulimit -f {s.workspace_quota_mb * 2048}; ulimit -n 1024; '
                  f'ulimit -v {s.memory_mb * 1024}; exec "$@"')
        return ['/bin/sh', '-c', script, 'nexus-bwrap', *args]


class BwrapExecutor:
    """`CommandExecutorPort` for one session: each command gets its own jail."""

    #: The jail ends with the command, so `sandbox_exec_async` cannot work (see `SandboxSession.exec_async`).
    supports_background = False

    #: Projected skills appear read-only at `/skills`; `/outputs` is the real jail path.
    skills_mount = '/skills'
    envs_mount = '/skill_envs'
    outputs_path = '/outputs'

    def __init__(self, backend: BwrapBackend, workspace: Path, outputs: Path, skills: Path | None = None,
                 envs: Path | None = None):
        self.backend, self.workspace, self.outputs, self.skills = backend, workspace, outputs, skills
        self.envs = envs

    async def run(self, command: str, *, cwd: str, timeout_seconds: float, output_limit: int,
                  env: dict[str, str] | None = None, stdin: str | None = None) -> ExecResult:
        from ... import paths
        paths.split(cwd)  # only /workspace and /outputs are valid working directories
        if find_binary(self.backend.binary) is None:
            raise SandboxError('sandbox_backend_unavailable', 'bwrap is not installed')
        argv = self.backend.limited(self.backend.jail_arguments(self.workspace, self.outputs, cwd, command, env, self.skills, self.envs))
        from ...disk_quota import ensure
        await asyncio.to_thread(ensure, self.backend.settings, self.workspace.parent)
        from ...cgroups import CommandCgroup
        group = CommandCgroup(self.backend.settings)
        if group.path is not None:
            offset = argv.index('--remount-ro')
            argv[offset:offset] = ['--ro-bind', str(group.path), '/sys/fs/cgroup']
        argv = group.wrap(argv)
        started = time.monotonic()
        try:
            return await self._capture(argv, timeout_seconds, output_limit, stdin, started)
        finally:
            from ...lifecycle import drain
            await drain(group.close())

    async def _capture(self, argv, timeout_seconds, output_limit, stdin, started):
        process = await asyncio.create_subprocess_exec(
            *argv, stdin=asyncio.subprocess.PIPE if stdin is not None else asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env={'PATH': _PATH}, start_new_session=True)
        out, err = Sink(output_limit), Sink(output_limit)
        timed_out = False

        def kill() -> None:
            # The jail has its own PID namespace: ending bwrap (the namespace's parent) ends everything inside.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

        try:
            await asyncio.wait_for(asyncio.gather(out.drain(process.stdout), err.drain(process.stderr), process.wait(),
                                                  feed_stdin(process, stdin)), timeout_seconds)
        except asyncio.TimeoutError:
            timed_out = True
            kill()
            await process.wait()
        except BaseException:
            kill()  # cancellation: never leave a jail behind
            raise
        return ExecResult(None if timed_out else process.returncode, timed_out, out.text(), err.text(),
                          out.truncated, err.truncated, int((time.monotonic() - started) * 1000))

    async def close(self) -> None:
        return None  # nothing outlives a command
