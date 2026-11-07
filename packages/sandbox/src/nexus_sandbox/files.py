"""File store on host directories mounted into the sandbox as `/workspace` and `/outputs`.

Both the docker and the local backend use it: the container sees the same directories under the same
virtual names, so what the tools write is what commands read. Every method resolves through `paths.resolve`,
writes are atomic (temporary file in the same directory, then replace), and sizes are bounded.
"""
from __future__ import annotations

import asyncio
import fnmatch
import os
import re
import tempfile
from pathlib import Path

from nexus_core.sandbox import FileChunk, FileEntry, SandboxError, SearchHit
from . import paths

#: Largest file `read_file` and `edit_file` will load; larger files are searched or read with commands.
MAX_READ_BYTES = 5_000_000
#: Largest single write through `write_file`.
MAX_WRITE_BYTES = 2_000_000
#: Images `read_image` hands to a vision model, by suffix, and their size limit.
IMAGE_TYPES = {'.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp', '.gif': 'image/gif'}
MAX_IMAGE_BYTES = 10_000_000
#: Search bounds: files visited, bytes read per file, and characters kept per hit.
SEARCH_MAX_FILES = 2000
SEARCH_MAX_FILE_BYTES = 1_000_000
HIT_CHARS = 300


class HostFileStore:
    """`FileStorePort` over two host directories."""

    def __init__(self, workspace: Path, outputs: Path, *, quota_bytes: int):
        self.roots = {'/workspace': workspace, '/outputs': outputs}
        for root in self.roots.values():
            root.mkdir(parents=True, exist_ok=True)
        self.quota_bytes = quota_bytes
        #: Bumped by every completed mutation, so a reader that cached content can tell it went stale.
        self.mutation_epoch = 0

    # ------------------------------------------------------------------ helpers

    def _used_bytes(self) -> int:
        total = 0
        for root in self.roots.values():
            for directory, _, names in os.walk(root, followlinks=False):
                for name in names:
                    try:
                        total += os.lstat(os.path.join(directory, name)).st_size
                    except OSError:
                        pass
        return total

    def _replace(self, host: Path, payload: bytes) -> None:
        """Atomic write: a temporary file in the same directory, then replace; the mutation counter moves after."""
        handle, temporary = tempfile.mkstemp(dir=host.parent, prefix='.write-')
        try:
            with os.fdopen(handle, 'wb') as stream:
                stream.write(payload)
            os.replace(temporary, host)
        except BaseException:
            Path(temporary).unlink(missing_ok=True)
            raise
        self.mutation_epoch += 1

    def _entry(self, host: Path) -> FileEntry:
        info = host.lstat()
        kind = 'dir' if host.is_dir() and not host.is_symlink() else 'file'
        return FileEntry(paths.virtual_of(host.parent, self.roots).rstrip('/') + '/' + host.name, kind,
                         0 if kind == 'dir' else info.st_size)

    # ------------------------------------------------------------------ port

    async def list_files(self, path: str, *, limit: int) -> list[FileEntry]:
        return await asyncio.to_thread(self._list, path, limit)

    def _list(self, path: str, limit: int) -> list[FileEntry]:
        if path.rstrip('/') in ('', '/'):
            return [FileEntry(root, 'dir') for root in self.roots]
        host = paths.resolve(path, self.roots, must_exist=True)
        if not host.is_dir():
            raise SandboxError('sandbox_not_a_directory')
        return [self._entry(child) for child in sorted(host.iterdir(), key=lambda p: p.name)[:limit]]

    async def read_file(self, path: str, *, start_line: int, max_lines: int) -> FileChunk:
        return await asyncio.to_thread(self._read, path, start_line, max_lines)

    def _read(self, path: str, start_line: int, max_lines: int) -> FileChunk:
        host = paths.resolve(path, self.roots, must_exist=True)
        if host.is_dir():
            raise SandboxError('sandbox_is_a_directory')
        size = host.stat().st_size
        if size > MAX_READ_BYTES:
            raise SandboxError('sandbox_file_too_large', 'use sandbox_search_files, or read a part with a command')
        data = host.read_bytes()
        if b'\x00' in data[:8192]:
            raise SandboxError('sandbox_binary_file')
        lines = data.decode('utf-8', 'replace').splitlines()
        first = max(1, start_line)
        chosen = lines[first - 1:first - 1 + max_lines]
        following = first + len(chosen) if first - 1 + len(chosen) < len(lines) else None
        return FileChunk('\n'.join(chosen), first, len(lines), following, size)

    async def read_image(self, path: str) -> tuple[bytes, str]:
        return await asyncio.to_thread(self._image, path)

    def _image(self, path: str) -> tuple[bytes, str]:
        host = paths.resolve(path, self.roots, must_exist=True)
        mime = IMAGE_TYPES.get(host.suffix.lower())
        if mime is None or host.is_dir():
            raise SandboxError('sandbox_not_an_image', 'supported: png, jpg, jpeg, webp, gif')
        if host.stat().st_size > MAX_IMAGE_BYTES:
            raise SandboxError('sandbox_file_too_large')
        return host.read_bytes(), mime

    async def write_file(self, path: str, content: str, *, append: bool) -> int:
        return await asyncio.to_thread(self._write, path, content, append)

    def _write(self, path: str, content: str, append: bool) -> int:
        payload = content.encode('utf-8')
        if len(payload) > MAX_WRITE_BYTES:
            raise SandboxError('sandbox_write_too_large', 'split the content over several calls with append=true')
        host = paths.resolve(path, self.roots)
        if host in self.roots.values() or host.is_dir():
            raise SandboxError('sandbox_is_a_directory')
        if self._used_bytes() + len(payload) > self.quota_bytes:
            raise SandboxError('sandbox_quota_exceeded')
        host.parent.mkdir(parents=True, exist_ok=True)
        previous = host.read_bytes() if append and host.exists() else b''
        self._replace(host, previous + payload)
        return len(payload)

    async def edit_file(self, path: str, old: str, new: str) -> int:
        return await asyncio.to_thread(self._edit, path, old, new)

    def _edit(self, path: str, old: str, new: str) -> int:
        if not old:
            raise SandboxError('sandbox_edit_empty_match')
        host = paths.resolve(path, self.roots, must_exist=True)
        if host.is_dir() or host.stat().st_size > MAX_READ_BYTES:
            raise SandboxError('sandbox_file_too_large' if not host.is_dir() else 'sandbox_is_a_directory')
        text = host.read_bytes().decode('utf-8')
        count = text.count(old)
        if count != 1:
            # Zero or several matches: the model must add context or fix the text; report how many there were.
            raise SandboxError('sandbox_edit_not_found' if count == 0 else 'sandbox_edit_ambiguous', f'{count} matches')
        updated = text.replace(old, new, 1).encode('utf-8')
        if self._used_bytes() - len(text.encode('utf-8')) + len(updated) > self.quota_bytes:
            raise SandboxError('sandbox_quota_exceeded')
        self._replace(host, updated)
        return 1

    async def search_files(self, query: str, path: str, *, glob: str, regex: bool, limit: int) -> list[SearchHit]:
        return await asyncio.to_thread(self._search, query, path, glob, regex, limit)

    def _search(self, query: str, path: str, glob: str, regex: bool, limit: int) -> list[SearchHit]:
        try:
            pattern = re.compile(query if regex else re.escape(query))
        except re.error:
            raise SandboxError('sandbox_pattern_invalid') from None
        start = paths.resolve(path, self.roots, must_exist=True)
        hits: list[SearchHit] = []
        visited = 0
        candidates = [start] if start.is_file() else (p for d, _, names in os.walk(start, followlinks=False)
                                                       for p in (Path(d, n) for n in sorted(names)))
        for host in candidates:
            if visited >= SEARCH_MAX_FILES or len(hits) >= limit:
                break
            if host.is_symlink() or not fnmatch.fnmatch(host.name, glob):
                continue
            visited += 1
            try:
                if host.stat().st_size > SEARCH_MAX_FILE_BYTES:
                    continue
                data = host.read_bytes()
            except OSError:
                continue
            if b'\x00' in data[:8192]:
                continue
            for number, line in enumerate(data.decode('utf-8', 'replace').splitlines(), 1):
                if pattern.search(line):
                    hits.append(SearchHit(paths.virtual_of(host, self.roots), number, line[:HIT_CHARS]))
                    if len(hits) >= limit:
                        break
        return hits

    def collect_outputs(self) -> list[tuple[str, int]]:
        """(virtual path, size) of every regular file under `/outputs`, for artifact registration."""
        found = []
        base = self.roots['/outputs']
        for directory, _, names in os.walk(base, followlinks=False):
            for name in sorted(names):
                host = Path(directory, name)
                if not host.is_symlink():
                    found.append((paths.virtual_of(host, self.roots), host.stat().st_size))
        return found
