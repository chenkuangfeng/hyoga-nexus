"""One sandbox session: a file store plus a command executor, bounded by the agent's limits.

`SandboxSession` implements `nexus_core.sandbox.SandboxSessionPort`. It is created per Run from the
manager's lease and carries the limits the agent chose, clamped to what the deployment allows.
"""
from __future__ import annotations

import asyncio
import re
import shlex
import time
import uuid

from nexus_core.sandbox import ExecResult, FileChunk, FileEntry, JobStatus, SandboxError, SearchHit
from pathlib import Path

from . import paths, skills as projection
from .contracts import CommandExecutorPort, FileStorePort


#: Background jobs keep their state in `/workspace/.jobs/<id>/` (`out`, `rc`, `pid`, `started`), so any worker can
#: read it and a restart loses nothing. At most this many run at once in one session.
MAX_JOBS = 4
_JOB_ID = re.compile(r'j[0-9a-f]{10}')
JOBS_DIR = '/workspace/.jobs'
#: Largest standard input of one command, in bytes (WeKnora's limit for `shell_exec`).
MAX_STDIN_BYTES = 65_536
_ENV_NAME = re.compile(r'^[A-Z_][A-Z0-9_]{0,63}$')
_MAX_ENV_VALUE = 4096


class SandboxSession:
    """Session surface for the tools. File operations validate before reaching the store."""

    def __init__(self, files: FileStorePort, executor: CommandExecutorPort, *, default_timeout: float,
                 max_timeout: float, output_limit: int, skills_dir: Path | None = None, envs_dir: Path | None = None):
        self.files, self.executor, self.skills_dir = files, executor, skills_dir
        self.envs_dir = envs_dir
        self.default_timeout, self.max_timeout, self.output_limit = default_timeout, max_timeout, output_limit

    async def list_files(self, path: str, *, limit: int) -> list[FileEntry]:
        return await self.files.list_files(path, limit=limit)

    async def read_file(self, path: str, *, start_line: int, max_lines: int) -> FileChunk:
        return await self.files.read_file(path, start_line=start_line, max_lines=max_lines)

    async def read_image(self, path: str) -> tuple[bytes, str]:
        return await self.files.read_image(path)

    async def write_file(self, path: str, content: str, *, append: bool) -> int:
        return await self.files.write_file(path, content, append=append)

    async def edit_file(self, path: str, old: str, new: str) -> int:
        return await self.files.edit_file(path, old, new)

    async def search_files(self, query: str, path: str, *, glob: str, regex: bool, limit: int) -> list[SearchHit]:
        return await self.files.search_files(query, path, glob=glob, regex=regex, limit=limit)

    async def exec(self, command: str, *, cwd: str, timeout_seconds: float,
                   env: dict[str, str] | None = None, stdin: str | None = None,
                   max_timeout: float | None = None) -> ExecResult:
        """Run `command`. `stdin` (at most 65536 bytes) becomes its standard input; `env` adds variables and is for
        trusted callers such as `exec_skill`, never taken from a model argument. `max_timeout` replaces the session's
        ceiling for this call (skill scripts have their own, higher one)."""
        if not command.strip() or len(command) > 20_000:
            raise SandboxError('sandbox_command_invalid')
        paths.split(cwd)
        if stdin is not None and (not isinstance(stdin, str) or len(stdin.encode('utf-8')) > MAX_STDIN_BYTES):
            raise SandboxError('sandbox_stdin_too_large', f'standard input is limited to {MAX_STDIN_BYTES} bytes')
        for key, value in (env or {}).items():
            if not _ENV_NAME.match(key) or not isinstance(value, str) or len(value) > _MAX_ENV_VALUE or '\x00' in value:
                raise SandboxError('sandbox_env_invalid')
        timeout = min(timeout_seconds or self.default_timeout, max_timeout or self.max_timeout)
        return await self.executor.run(command, cwd=cwd, timeout_seconds=timeout, output_limit=self.output_limit,
                                       env=env or None, stdin=stdin)

    # ------------------------------------------------------------------ skills

    def project_skill(self, name: str, content_hash: str, files: dict[str, str | bytes]) -> str:
        """Make a skill's files readable (never writable) inside the sandbox; returns its directory as a command sees it."""
        mount = getattr(self.executor, 'skills_mount', None)
        if self.skills_dir is None or mount is None:
            raise SandboxError('sandbox_skills_unavailable')
        projection.project(self.skills_dir, name, content_hash, files)
        return f"{mount.rstrip('/')}/{projection.directory_name(name, content_hash)}"

    def skill_environment(self, skill_dir: str, env_name: str | None = None) -> dict[str, str]:
        """Variables a skill script finds: its own directory and the directory for deliverables, and, when it has a
        built dependency environment (`env_name`), where that environment's packages are (``NODE_PATH``)."""
        variables = {'NEXUS_SKILL_DIR': skill_dir,
                     'NEXUS_SKILL_OUTPUT_DIR': getattr(self.executor, 'outputs_path', '/outputs')}
        base = self.env_path(env_name) if env_name else None
        if base is not None:
            variables['NODE_PATH'] = f'{base}/node/node_modules'
            variables['VIRTUAL_ENV'] = f'{base}/venv'
        return variables

    def env_path(self, env_name: str) -> str | None:
        """Where a built environment is visible to a command, or None when it was not built (or cannot be mounted)."""
        mount = getattr(self.executor, 'envs_mount', None)
        if self.envs_dir is None or mount is None or '/' in env_name or env_name.startswith('.'):
            return None
        return f"{mount.rstrip('/')}/{env_name}" if (self.envs_dir / env_name).is_dir() else None

    def outputs(self) -> list[tuple[str, int]]:
        """Files under `/outputs` for artifact registration."""
        collect = getattr(self.files, 'collect_outputs', None)
        return collect() if collect else []

    # ------------------------------------------------------------------ background jobs

    async def exec_async(self, command: str, *, cwd: str, timeout_seconds: float) -> str:
        """Start `command` in the background and return its job id. Output goes to a file; see `job_status`.

        The command runs in its own session (`setsid`) under `timeout`, so cancelling or timing out ends the whole
        process tree. Working directories are limited to `/workspace` so bookkeeping paths stay relative.
        """
        if not command.strip() or len(command) > 20_000:
            raise SandboxError('sandbox_command_invalid')
        root, parts = paths.split(cwd)
        if root != '/workspace':
            raise SandboxError('sandbox_path_invalid', 'background commands run under /workspace')
        if not getattr(self.executor, 'supports_background', True):
            # A bwrap jail ends with its launcher shell (PID namespace), so a detached job could not outlive it.
            raise SandboxError('sandbox_background_unsupported', 'this sandbox backend cannot keep a command running after it returns')
        running = [job for job in await self._jobs() if (await self._finished(job)) is None]
        if len(running) >= MAX_JOBS:
            raise SandboxError('sandbox_too_many_jobs', f'at most {MAX_JOBS} background commands at once; cancel or wait for one')
        job_id = 'j' + uuid.uuid4().hex[:10]
        timeout = int(min(timeout_seconds or self.default_timeout, self.max_timeout))
        directory = f'.jobs/{job_id}'
        target = '/'.join(parts)
        enter = f'"$W/{target}"' if target else '"$W"'
        # $W is the workspace root, exported so the detached shell can find the bookkeeping files after `cd`.
        # The shell leads its own session, so its process group is the job's whole tree. A watchdog in that group
        # records the timeout (rc 124) and kills the group; the shell records the real exit code and then kills the
        # group too, so nothing the command left behind outlives the job. (`timeout(1)` would move the command to
        # a group of its own, out of reach of `job_cancel`.)
        inner = (f'cd {enter} 2>"$W/{directory}/out" || {{ echo 1 > "$W/{directory}/rc"; kill -KILL 0; }}; '
                 f'( sleep {timeout}; echo 124 > "$W/{directory}/rc"; kill -KILL 0 ) & '
                 f'sh -c {shlex.quote(command)} >>"$W/{directory}/out" 2>&1; echo $? > "$W/{directory}/rc"; kill -KILL 0')
        script = (f'W=$(pwd); export W; mkdir -p {directory} && date +%s > {directory}/started '
                  f'&& (setsid sh -c {shlex.quote(inner)} >/dev/null 2>&1 </dev/null & echo $! > {directory}/pid)')
        started = await self.executor.run(script, cwd='/workspace', timeout_seconds=15, output_limit=2000)
        if started.exit_code != 0:
            raise SandboxError('sandbox_job_start_failed', (started.stderr or started.stdout)[:200])
        return job_id

    async def _jobs(self) -> list[str]:
        try:
            entries = await self.files.list_files(JOBS_DIR, limit=200)
        except SandboxError:
            return []
        return [entry.path.rsplit('/', 1)[-1] for entry in entries if entry.kind == 'dir' and _JOB_ID.fullmatch(entry.path.rsplit('/', 1)[-1])]

    async def _read(self, job_id: str, name: str) -> str | None:
        try:
            chunk = await self.files.read_file(f'{JOBS_DIR}/{job_id}/{name}', start_line=1, max_lines=100_000)
        except SandboxError:
            return None
        return chunk.text

    async def _finished(self, job_id: str) -> int | None:
        """Exit code once the job wrote `rc`; None while it runs (a missing or unreadable code reads as -1)."""
        text = await self._read(job_id, 'rc')
        if text is None:
            return None
        try:
            return int(text.strip())
        except ValueError:
            return -1

    async def job_status(self, job_id: str, *, wait_seconds: float = 0, tail_chars: int = 4000) -> JobStatus:
        """State and recent output of a job; waits up to `wait_seconds` for it to finish."""
        if not _JOB_ID.fullmatch(job_id or ''):
            raise SandboxError('sandbox_job_not_found')
        if await self._read(job_id, 'started') is None:
            raise SandboxError('sandbox_job_not_found')
        deadline = time.monotonic() + max(0.0, min(wait_seconds, 60.0))
        while True:
            code = await self._finished(job_id)
            if code is not None or time.monotonic() >= deadline:
                break
            await asyncio.sleep(0.4)
        text = await self._read(job_id, 'out') or ''
        cancelled = (await self._read(job_id, 'cancelled')) is not None
        started = float((await self._read(job_id, 'started') or '0').strip() or 0)
        state = 'cancelled' if cancelled else 'finished' if code is not None else 'running'
        truncated = len(text) > tail_chars
        return JobStatus(job_id, state, None if cancelled else code, text[-tail_chars:], truncated, max(0.0, time.time() - started))

    async def job_cancel(self, job_id: str) -> JobStatus:
        """Kill a running job's process group. A finished job is left as it is."""
        status = await self.job_status(job_id)
        if status.state == 'running':
            pid = (await self._read(job_id, 'pid') or '').strip()
            if pid.isdigit():
                await self.executor.run(f'kill -9 -- -{pid} 2>/dev/null; echo cancelled > .jobs/{job_id}/cancelled; true',
                                        cwd='/workspace', timeout_seconds=10, output_limit=500)
            status = await self.job_status(job_id)
        return status

    async def close_jobs(self) -> int:
        """Cancel every job still running (the Run that started them is over). Returns how many were cancelled."""
        cancelled = 0
        for job_id in await self._jobs():
            if (await self._finished(job_id)) is None and (await self._read(job_id, 'cancelled')) is None:
                await self.job_cancel(job_id)
                cancelled += 1
        return cancelled
