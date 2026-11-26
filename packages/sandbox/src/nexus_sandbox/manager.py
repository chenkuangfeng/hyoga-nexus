"""Leases: one workspace (and, for docker, one container; for bwrap, one jail per command) per (tenant, session).

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
from .backends.bwrap import BwrapBackend, BwrapExecutor
from .backends.local import LocalExecutor
from .backends.remote import RemoteExecutor
from .files import HostFileStore
from . import leases
from .session import SandboxSession
from .settings import SandboxSettings
from nexus_core.sandbox import SandboxError

_ID = re.compile(r'[A-Za-z0-9_-]{1,64}')


class _TouchingExecutor:
    """Forwards to the real executor and records the use time around each command.

    `reap` judges idleness by the last use. Without this, a Run that outlasts `idle_seconds` would have its
    container removed in the middle of a command, because the time was only set when the session was created.
    Other attributes (mount paths, `close`, `supports_background`) pass through unchanged.
    """

    def __init__(self, inner, touch, settings=None):
        self._inner, self._touch, self._settings = inner, touch, settings

    async def run(self, *args, **kwargs):
        self._touch()
        try:
            if self._settings is not None:
                async with leases.hold(self._settings.root, self._inner.name):
                    from .disk_quota import ensure
                    import asyncio
                    await asyncio.to_thread(ensure, self._settings, self._inner.workspace.parent)
                    return await self._inner.run(*args, **kwargs)
            return await self._inner.run(*args, **kwargs)
        finally:
            self._touch()

    def __getattr__(self, name):
        return getattr(self._inner, name)


class SandboxManager:
    """Creates sessions and reclaims idle ones. One instance per process."""

    def __init__(self, settings: SandboxSettings, *, docker: DockerBackend | None = None):
        self.settings = settings
        self.docker = docker or (DockerBackend(settings) if settings.backend == 'docker' else None)
        self.bwrap = BwrapBackend(settings) if settings.backend == 'bwrap' else None
        self._last_used: dict[str, float] = {}
        self._executors: dict[str, object] = {}

    def _directories(self, tenant_id: str, session_id: str) -> tuple[Path, Path]:
        if not _ID.fullmatch(str(tenant_id)) or not _ID.fullmatch(str(session_id)):
            raise SandboxError('sandbox_session_invalid')
        base = self.settings.root.resolve() / str(tenant_id) / str(session_id)
        return base / 'workspace', base / 'outputs'

    def session(self, tenant_id: str, session_id: str, *, default_timeout: float = 30, output_limit: int = 20_000,
                execution_id: str | None = None) -> SandboxSession:
        """The session for this (tenant, session), creating directories on first use. No container starts here."""
        workspace, outputs = self._directories(tenant_id, session_id)
        skills = workspace.parent / 'skills'
        skills.mkdir(parents=True, exist_ok=True)  # the mount source must exist before a container starts
        envs = self.settings.envs_root
        envs.mkdir(parents=True, exist_ok=True)
        files = HostFileStore(workspace, outputs, quota_bytes=self.settings.workspace_quota_mb * 1024 * 1024,
                              mutation_lock=(self.settings.root, leases.session_name(tenant_id, session_id)))
        key = f'{tenant_id}/{session_id}'
        if self.settings.backend == 'docker':
            container_session = str(session_id) if execution_id is None else f'{session_id}-{execution_id}'
            executor = DockerExecutor(self.docker, container_name(str(tenant_id), container_session, self.settings.profile, self.settings.configuration_id), workspace, outputs, skills, envs)
        elif self.settings.backend == 'bwrap':
            executor = BwrapExecutor(self.bwrap, workspace, outputs, skills, envs)
        elif self.settings.backend == 'local':
            executor = LocalExecutor(files.roots, self.settings.env_passthrough, skills, envs)
        else:
            executor = RemoteExecutor(self.settings, str(tenant_id), str(session_id))
        self._last_used[key] = time.monotonic()
        self._executors[key] = executor
        executor = _TouchingExecutor(executor, lambda: self._last_used.__setitem__(key, time.monotonic()),
                                     self.settings if self.docker else None)
        return SandboxSession(files, executor, default_timeout=default_timeout,
                              max_timeout=self.settings.exec_timeout_max_seconds, output_limit=output_limit, skills_dir=skills,
                              envs_dir=envs)

    async def release(self, tenant_id: str, session_id: str) -> None:
        """Remove the session's container now (the workspace directory stays)."""
        key = f'{tenant_id}/{session_id}'
        executor = self._executors.pop(key, None)
        self._last_used.pop(key, None)
        if executor is not None:
            if self.docker is not None:
                async with leases.hold(self.settings.root, executor.name):
                    await executor.close()
            else:
                await executor.close()

    async def reap(self, *, now: float | None = None, only_names: set[str] | None = None) -> list[str]:
        """Remove idle containers and containers this process does not know. Returns the removed names."""
        if self.docker is None:
            return []
        now = time.monotonic() if now is None else now
        live = {container_name(*key.split('/', 1), self.settings.profile, self.settings.configuration_id) for key, used in self._last_used.items()
                if now - used < self.settings.idle_seconds}
        removed = []
        for name in await self.docker.list_managed():
            if name not in live and (only_names is None or name in only_names):
                lock = leases.try_reap(self.settings.root, name, 0 if only_names else self.settings.idle_seconds)
                if lock is not None:
                    try:
                        await self.docker.remove(name)
                        removed.append(name)
                    finally:
                        lock.close()
        for key in [k for k, used in self._last_used.items() if now - used >= self.settings.idle_seconds]:
            self._last_used.pop(key, None)
            self._executors.pop(key, None)
        return removed
