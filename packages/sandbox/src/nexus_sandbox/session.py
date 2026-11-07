"""One sandbox session: a file store plus a command executor, bounded by the agent's limits.

`SandboxSession` implements `nexus_core.sandbox.SandboxSessionPort`. It is created per Run from the
manager's lease and carries the limits the agent chose, clamped to what the deployment allows.
"""
from __future__ import annotations

from nexus_core.sandbox import ExecResult, FileChunk, FileEntry, SandboxError, SearchHit
from . import paths
from .contracts import CommandExecutorPort, FileStorePort


class SandboxSession:
    """Session surface for the tools. File operations validate before reaching the store."""

    def __init__(self, files: FileStorePort, executor: CommandExecutorPort, *, default_timeout: float,
                 max_timeout: float, output_limit: int):
        self.files, self.executor = files, executor
        self.default_timeout, self.max_timeout, self.output_limit = default_timeout, max_timeout, output_limit

    async def list_files(self, path: str, *, limit: int) -> list[FileEntry]:
        return await self.files.list_files(path, limit=limit)

    async def read_file(self, path: str, *, start_line: int, max_lines: int) -> FileChunk:
        return await self.files.read_file(path, start_line=start_line, max_lines=max_lines)

    async def write_file(self, path: str, content: str, *, append: bool) -> int:
        return await self.files.write_file(path, content, append=append)

    async def edit_file(self, path: str, old: str, new: str) -> int:
        return await self.files.edit_file(path, old, new)

    async def search_files(self, query: str, path: str, *, glob: str, regex: bool, limit: int) -> list[SearchHit]:
        return await self.files.search_files(query, path, glob=glob, regex=regex, limit=limit)

    async def exec(self, command: str, *, cwd: str, timeout_seconds: float) -> ExecResult:
        if not command.strip() or len(command) > 20_000:
            raise SandboxError('sandbox_command_invalid')
        paths.split(cwd)
        timeout = min(timeout_seconds or self.default_timeout, self.max_timeout)
        return await self.executor.run(command, cwd=cwd, timeout_seconds=timeout, output_limit=self.output_limit)

    def outputs(self) -> list[tuple[str, int]]:
        """Files under `/outputs` for artifact registration."""
        collect = getattr(self.files, 'collect_outputs', None)
        return collect() if collect else []
