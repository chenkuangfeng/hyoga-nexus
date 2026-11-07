"""Local executor: runs commands as the server user in the workspace directory.

NOT an isolation boundary. It exists for development and for tests of the tools and the session. The
sandbox group is never offered with this backend unless the operator sets `allow_local = true` and the
platform runs in development auth mode. Commands see host paths, not `/workspace`; only `cwd` is translated.
"""
from __future__ import annotations

import asyncio
import os
import signal
import time
from pathlib import Path

from nexus_core.sandbox import ExecResult
from ..output import Sink

CHILD_PATH = '/usr/local/bin:/usr/bin:/bin'


class LocalExecutor:
    """`CommandExecutorPort` on the host. The environment is built from scratch, never inherited."""

    def __init__(self, roots: dict[str, Path], forward: tuple[str, ...] = ()):
        self.roots = roots
        #: Host variable names forwarded into the command environment (the profile's `env_passthrough`).
        self.forward = forward

    async def run(self, command: str, *, cwd: str, timeout_seconds: float, output_limit: int) -> ExecResult:
        from ... import paths
        directory = paths.resolve(cwd, self.roots, must_exist=True)
        env = {'PATH': CHILD_PATH, 'HOME': str(self.roots['/workspace']), 'LANG': 'C.UTF-8', 'LC_ALL': 'C.UTF-8'}
        env.update({key: os.environ[key] for key in self.forward if key in os.environ})
        started = time.monotonic()
        process = await asyncio.create_subprocess_exec(
            '/bin/sh', '-c', command, cwd=str(directory), env=env, stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, start_new_session=True)
        out, err = Sink(output_limit), Sink(output_limit)
        timed_out = False

        async def finish() -> None:
            await asyncio.gather(out.drain(process.stdout), err.drain(process.stderr), process.wait())

        def kill() -> None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

        try:
            await asyncio.wait_for(finish(), timeout_seconds)
        except asyncio.TimeoutError:
            timed_out = True
            kill()
            await process.wait()
        except BaseException:
            kill()  # cancellation: never leave a process group behind
            raise
        return ExecResult(None if timed_out else process.returncode, timed_out, out.text(), err.text(),
                          out.truncated, err.truncated, int((time.monotonic() - started) * 1000))

    async def close(self) -> None:
        return None
