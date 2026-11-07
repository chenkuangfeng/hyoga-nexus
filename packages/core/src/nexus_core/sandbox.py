"""Vendor-neutral sandbox contracts (openspec 2026-11-07-tool-expansion, section 3).

The tools package depends only on core, so the session surface the sandbox tools call lives here; the
`nexus_sandbox` package implements it. Models see virtual paths (`/workspace`, `/outputs`) only; host paths
never cross this boundary. Every failure is a `SandboxError` whose `code` is stable and safe to show.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

#: The only virtual roots a model can name. `/workspace` is read-write scratch space; files under `/outputs`
#: are collected as artifacts when the Run ends.
VIRTUAL_ROOTS = ('/workspace', '/outputs')


class SandboxError(Exception):
    """A refused or failed sandbox operation. `code` is a stable identifier such as `sandbox_path_invalid`."""

    def __init__(self, code: str, detail: str = ''):
        super().__init__(code)
        self.code, self.detail = code, detail


@dataclass(frozen=True)
class FileEntry:
    """One directory entry, by virtual path."""
    path: str
    kind: Literal['file', 'dir']
    size: int = 0


@dataclass(frozen=True)
class FileChunk:
    """A line range of a text file. `next_line` is None at the end."""
    text: str
    first_line: int
    total_lines: int
    next_line: int | None
    size: int


@dataclass(frozen=True)
class SearchHit:
    """One matching line."""
    path: str
    line: int
    text: str


@dataclass(frozen=True)
class ExecResult:
    """Outcome of one command. `exit_code` is None when it was killed on timeout."""
    exit_code: int | None
    timed_out: bool
    stdout: str
    stderr: str
    stdout_truncated: bool
    stderr_truncated: bool
    duration_ms: int


@dataclass(frozen=True)
class SkillRun:
    """Outcome of `exec_skill`: either a refusal (`refused` is a stable code) or the command's result.

    `hint` is a short recovery direction for a failed run (a missing module or interpreter); it is empty otherwise.
    """
    skill: str
    version: int
    script: str
    refused: str = ''
    result: ExecResult | None = None
    hint: str = ''


@dataclass(frozen=True)
class JobStatus:
    """State of a background command. `exit_code` is set once `state` is `finished` (None when killed)."""
    job_id: str
    state: Literal['running', 'finished', 'cancelled']
    exit_code: int | None
    output: str
    output_truncated: bool
    elapsed_seconds: float


class SandboxSessionPort(Protocol):
    """What the sandbox tools may do for one (tenant, session). Implementations enforce every limit."""

    async def list_files(self, path: str, *, limit: int) -> list[FileEntry]: ...
    async def read_file(self, path: str, *, start_line: int, max_lines: int) -> FileChunk: ...
    async def write_file(self, path: str, content: str, *, append: bool) -> int: ...
    async def edit_file(self, path: str, old: str, new: str) -> int: ...
    async def search_files(self, query: str, path: str, *, glob: str, regex: bool, limit: int) -> list[SearchHit]: ...
    async def read_image(self, path: str) -> tuple[bytes, str]: ...
    async def exec(self, command: str, *, cwd: str, timeout_seconds: float,
                   env: dict[str, str] | None = None, stdin: str | None = None,
                   max_timeout: float | None = None) -> ExecResult: ...
    def project_skill(self, name: str, content_hash: str, files: dict[str, str | bytes]) -> str: ...
    def skill_environment(self, skill_dir: str, env_name: str | None = None) -> dict[str, str]: ...
    def env_path(self, env_name: str) -> str | None: ...
    async def exec_async(self, command: str, *, cwd: str, timeout_seconds: float) -> str: ...
    async def job_status(self, job_id: str, *, wait_seconds: float, tail_chars: int) -> JobStatus: ...
    async def job_cancel(self, job_id: str) -> JobStatus: ...
