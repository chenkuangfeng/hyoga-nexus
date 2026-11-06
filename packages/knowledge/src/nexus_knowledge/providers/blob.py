"""Storage backend port for original files; K1 implements the local directory (``local``).

Keys are relative POSIX paths built by the platform (``tenant/kb/document/version``); the local store
rejects absolute paths and ``..`` so a key can never escape its root. Writes go to a temporary file and are
renamed into place, so a crash never leaves a partial file under a valid key. Other providers (MinIO, S3,
COS, OSS, TOS) are planned and listed in the capability catalog.
"""
from __future__ import annotations

import asyncio
import os
import tempfile
from abc import ABC, abstractmethod
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from .. import capabilities


class BlobStoreError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class BlobStore(ABC):
    provider: str = ''

    @abstractmethod
    async def put(self, key: str, data: bytes) -> None: ...

    @abstractmethod
    async def get(self, key: str) -> bytes: ...

    @abstractmethod
    async def delete(self, key: str) -> None:
        """Delete a key; a missing key is not an error."""

    @abstractmethod
    async def ping(self) -> dict[str, Any]: ...


class LocalBlobStore(BlobStore):
    provider = 'local'

    def __init__(self, config: Mapping[str, Any]) -> None:
        root = str(config.get('root') or '').strip()
        if not root:
            raise BlobStoreError('invalid_config', 'local storage needs a root directory')
        self.root = Path(root).resolve()

    def _path(self, key: str) -> Path:
        pure = PurePosixPath(key)
        if not key or pure.is_absolute() or '..' in pure.parts:
            raise BlobStoreError('invalid_key', f'invalid storage key: {key!r}')
        return self.root.joinpath(*pure.parts)

    async def put(self, key: str, data: bytes) -> None:
        path = self._path(key)

        def work():
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=path.parent, prefix='.upload-')
            try:
                with os.fdopen(fd, 'wb') as handle:
                    handle.write(data)
                os.replace(tmp, path)
            except BaseException:
                Path(tmp).unlink(missing_ok=True)
                raise
        await asyncio.to_thread(work)

    async def get(self, key: str) -> bytes:
        path = self._path(key)
        try:
            return await asyncio.to_thread(path.read_bytes)
        except FileNotFoundError as exc:
            raise BlobStoreError('not_found', f'stored file is missing: {key}') from exc

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self._path(key).unlink, True)

    async def ping(self) -> dict[str, Any]:
        def work():
            self.root.mkdir(parents=True, exist_ok=True)
            probe = self.root / '.nexus-probe'
            probe.write_bytes(b'ok')
            probe.unlink()
        await asyncio.to_thread(work)
        return {'provider': 'local', 'root': str(self.root)}


_PROVIDERS = {'local': LocalBlobStore}
capabilities.mark_available('storage_provider', 'local')


def open_blob_store(provider: str, config: Mapping[str, Any]) -> BlobStore:
    if provider not in _PROVIDERS:
        capabilities.require_available('storage_provider', provider)
    return _PROVIDERS[provider](config)
