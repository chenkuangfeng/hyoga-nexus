"""Ports of the sandbox (architecture 2.9) and the session surface the tools use.

`CommandExecutorPort` runs commands and `FileStorePort` reads and writes files; a backend supplies one of
each and `SandboxSession` composes them into the `SandboxSessionPort` the tools call. The vendor-neutral
types live in `nexus_core.sandbox` so the tools package does not depend on this one.
"""
from __future__ import annotations

from typing import Protocol

from nexus_core.sandbox import (ExecResult, FileChunk, FileEntry, SandboxError, SandboxSessionPort, SearchHit,
                                VIRTUAL_ROOTS)


class CommandExecutorPort(Protocol):
    """Run one command for one (tenant, session) workspace. Implementations enforce the limits."""

    async def run(self, command: str, *, cwd: str, timeout_seconds: float, output_limit: int,
                  env: dict[str, str] | None = None, stdin: str | None = None) -> ExecResult: ...
    async def close(self) -> None: ...


class FileStorePort(Protocol):
    """File access by virtual path. Implementations refuse anything that resolves outside the roots."""

    async def list_files(self, path: str, *, limit: int) -> list[FileEntry]: ...
    async def read_file(self, path: str, *, start_line: int, max_lines: int) -> FileChunk: ...
    async def read_image(self, path: str) -> tuple[bytes, str]: ...
    async def write_file(self, path: str, content: str, *, append: bool) -> int: ...
    async def edit_file(self, path: str, old: str, new: str) -> int: ...
    async def search_files(self, query: str, path: str, *, glob: str, regex: bool, limit: int) -> list[SearchHit]: ...


__all__ = ['CommandExecutorPort', 'ExecResult', 'FileChunk', 'FileEntry', 'FileStorePort', 'SandboxError',
           'SandboxSessionPort', 'SearchHit', 'VIRTUAL_ROOTS']
