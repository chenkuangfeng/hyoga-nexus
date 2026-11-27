"""Leases: one workspace (and, for docker, one container; for bwrap, one jail per command) per (tenant, session).

The tenant and session ids become directory names, so they are validated as UUID-like tokens first. A lease
is held by the Run using it; idle containers are removed after `idle_seconds` while the workspace directory
stays until the retention policy deletes it. `reap` also removes containers whose lease this process no
longer knows (left behind by a crash).
"""
from __future__ import annotations

import re
import os
import sys
import stat
import time
from pathlib import Path

from .backends.docker import DockerBackend, DockerExecutor, container_name
from .backends.bwrap import BwrapBackend, BwrapExecutor
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

    def __init__(self, inner, touch, settings=None, data_lock=None):
        self._inner, self._touch, self._settings, self._data_lock = inner, touch, settings, data_lock

    async def run(self, *args, **kwargs):
        self._touch()
        try:
            if self._data_lock is not None:
                async with leases.hold(*self._data_lock):
                    if self._settings is not None:
                        async with leases.hold(self._settings.root, self._inner.name):
                            from .disk_quota import ensure
                            import asyncio
                            await asyncio.to_thread(ensure, self._settings, self._inner.workspace.parent)
                            return await self._inner.run(*args, **kwargs)
                    return await self._inner.run(*args, **kwargs)
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
        self.bwrap = BwrapBackend(settings) if settings.backend in ('bwrap', 'local') else None
        self._last_used: dict[str, float] = {}
        self._executors: dict[str, object] = {}

    def _directories(self, tenant_id: str, session_id: str) -> tuple[Path, Path]:
        if not _ID.fullmatch(str(tenant_id)) or not _ID.fullmatch(str(session_id)):
            raise SandboxError('sandbox_session_invalid')
        base = self.settings.root.resolve() / str(tenant_id) / str(session_id)
        return base / 'workspace', base / 'outputs'

    def session(self, tenant_id: str, session_id: str, *, user_id: str | None = None,
                default_timeout: float = 30, output_limit: int = 20_000,
                execution_id: str | None = None) -> SandboxSession:
        """The session for this (tenant, session), creating directories on first use. No container starts here."""
        workspace, outputs = self._directories(tenant_id, session_id)
        user_root = None
        if user_id is not None:
            if not _ID.fullmatch(str(user_id)):
                raise SandboxError('sandbox_session_invalid')
            user_root = self.settings.root.resolve() / str(tenant_id) / 'users' / str(user_id)
        skills = (user_root / 'skills') if user_root is not None else (workspace.parent / 'skills')
        skills.mkdir(parents=True, exist_ok=True)  # the mount source must exist before a container starts
        data = user_root / 'data' if user_root is not None else None
        if data is not None:
            data.mkdir(parents=True, exist_ok=True)
            temporary = data / 'tmp'
            temporary.mkdir(exist_ok=True)
            # Never follow a workspace symlink while preparing/chowning a mount. These directories are
            # user writable at runtime, so a replaced mount root must fail closed before a new command.
            for directory in (user_root, data, temporary):
                try:
                    mode = directory.lstat().st_mode
                except OSError:
                    raise SandboxError('sandbox_workspace_invalid') from None
                if not stat.S_ISDIR(mode):
                    raise SandboxError('sandbox_workspace_invalid')
            if sys.platform.startswith('linux') and os.getuid() == 0:
                # Bwrap drops root before the script starts. Give the isolated execution uid access to this
                # one mounted user directory; the jail does not expose another user's directory.
                for directory in (data, temporary):
                    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                    try:
                        os.fchown(descriptor, 65534, 65534)
                        os.fchmod(descriptor, 0o700)
                    finally:
                        os.close(descriptor)
        envs = self.settings.envs_root
        envs.mkdir(parents=True, exist_ok=True)
        files = HostFileStore(workspace, outputs, quota_bytes=self.settings.workspace_quota_mb * 1024 * 1024,
                              mutation_lock=(self.settings.root, leases.session_name(tenant_id, session_id)))
        key = f'{tenant_id}/{session_id}'
        if self.settings.backend == 'docker':
            container_session = str(session_id) if execution_id is None else f'{session_id}-{execution_id}'
            config_id = self.settings.configuration_id + ('-user-data-v1' if data is not None else '')
            executor = DockerExecutor(self.docker, container_name(str(tenant_id), container_session, self.settings.profile, config_id), workspace, outputs, skills, envs, data)
        elif self.settings.backend == 'bwrap':
            executor = BwrapExecutor(self.bwrap, workspace, outputs, skills, envs, data)
        elif self.settings.backend == 'local':
            # Production local is a host-local workspace behind the same per-command jail as bwrap.
            # It must never silently fall back to the unrestricted LocalExecutor.
            from .backends.bwrap import find_binary
            if self.bwrap is None:
                self.bwrap = BwrapBackend(self.settings)
            if find_binary(self.bwrap.binary) is None or not sys.platform.startswith('linux'):
                raise SandboxError('sandbox_local_isolation_unavailable')
            executor = BwrapExecutor(self.bwrap, workspace, outputs, skills, envs, data)
        else:
            executor = RemoteExecutor(self.settings, str(tenant_id), str(session_id))
        self._last_used[key] = time.monotonic()
        self._executors[key] = executor
        data_lock = (self.settings.root, leases.session_name(tenant_id, 'user-' + str(user_id))) if data is not None else None
        executor = _TouchingExecutor(executor, lambda: self._last_used.__setitem__(key, time.monotonic()),
                                     self.settings if self.docker else None, data_lock)
        return SandboxSession(files, executor, default_timeout=default_timeout,
                              max_timeout=self.settings.exec_timeout_max_seconds, output_limit=output_limit, skills_dir=skills,
                              envs_dir=envs, data_dir=data)

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
