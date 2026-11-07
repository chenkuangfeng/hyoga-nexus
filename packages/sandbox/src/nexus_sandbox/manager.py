"""Leases: one workspace (and, for docker, one container) per (tenant, session).

The tenant and session ids become directory names, so they are validated as UUID-like tokens first. A lease
is held by the Run using it; idle containers are removed after `idle_seconds` while the workspace directory
stays until the retention policy deletes it. `reap` also removes containers whose lease this process no
longer knows (left behind by a crash).
"""
from __future__ import annotations

import re
import time
from pathlib import Path

from .backends.docker import DockerBackend, DockerExecutor, container_name
from .backends.local import LocalExecutor
from .files import HostFileStore
from .session import SandboxSession
from .settings import SandboxSettings
from nexus_core.sandbox import SandboxError

_ID = re.compile(r'[A-Za-z0-9_-]{1,64}')


class SandboxManager:
    """Creates sessions and reclaims idle ones. One instance per process."""

    def __init__(self, settings: SandboxSettings, *, docker: DockerBackend | None = None):
        self.settings = settings
        self.docker = docker or (DockerBackend(settings) if settings.backend == 'docker' else None)
        self._last_used: dict[str, float] = {}
        self._executors: dict[str, object] = {}

    def _directories(self, tenant_id: str, session_id: str) -> tuple[Path, Path]:
        if not _ID.fullmatch(str(tenant_id)) or not _ID.fullmatch(str(session_id)):
            raise SandboxError('sandbox_session_invalid')
        base = self.settings.root.resolve() / str(tenant_id) / str(session_id)
        return base / 'workspace', base / 'outputs'

    def session(self, tenant_id: str, session_id: str, *, default_timeout: float = 30, output_limit: int = 20_000) -> SandboxSession:
        """The session for this (tenant, session), creating directories on first use. No container starts here."""
        workspace, outputs = self._directories(tenant_id, session_id)
        files = HostFileStore(workspace, outputs, quota_bytes=self.settings.workspace_quota_mb * 1024 * 1024)
        key = f'{tenant_id}/{session_id}'
        if self.settings.backend == 'docker':
            executor = DockerExecutor(self.docker, container_name(str(tenant_id), str(session_id)), workspace, outputs)
        else:
            executor = LocalExecutor(files.roots)
        self._last_used[key] = time.monotonic()
        self._executors[key] = executor
        return SandboxSession(files, executor, default_timeout=default_timeout,
                              max_timeout=self.settings.exec_timeout_max_seconds, output_limit=output_limit)

    async def release(self, tenant_id: str, session_id: str) -> None:
        """Remove the session's container now (the workspace directory stays)."""
        key = f'{tenant_id}/{session_id}'
        executor = self._executors.pop(key, None)
        self._last_used.pop(key, None)
        if executor is not None:
            await executor.close()

    async def reap(self, *, now: float | None = None) -> list[str]:
        """Remove idle containers and containers this process does not know. Returns the removed names."""
        if self.docker is None:
            return []
        now = time.monotonic() if now is None else now
        live = {container_name(*key.split('/', 1)) for key, used in self._last_used.items()
                if now - used < self.settings.idle_seconds}
        removed = []
        for name in await self.docker.list_managed():
            if name not in live:
                await self.docker.remove(name)
                removed.append(name)
        for key in [k for k, used in self._last_used.items() if now - used >= self.settings.idle_seconds]:
            self._last_used.pop(key, None)
            self._executors.pop(key, None)
        return removed
