"""Concurrency limit on background model calls, per model (WeKnora ``registerModelConcurrencyLimiter``).

Background jobs (memory capture and consolidation, knowledge enrichment) share a provider's rate limit with
interactive Runs. ``[model_limits].max_background_per_model`` caps how many of those calls run at once for one
model; interactive Runs are never held back. The cap is off unless set.

Counting is per process, plus across processes when the Redis bus is installed: each holder takes a lease in a
sorted set that expires on its own, so a crashed worker cannot keep a slot forever.
"""
from __future__ import annotations

import asyncio
import contextlib
import secrets
import threading
import time
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

from nexus_core.deployment import CONFIG_RELATIVE_PATH, DeploymentConfigError, section

_FILE = CONFIG_RELATIVE_PATH.as_posix()
LEASE_SECONDS = 600
POLL_SECONDS = 0.2
#: A call that cannot get a slot this long gives up with the error below; the job is retried by its runner.
MAX_WAIT_SECONDS = 300.0

_ACQUIRE = """
redis.call("zremrangebyscore", KEYS[1], "-inf", ARGV[1])
if redis.call("zcard", KEYS[1]) >= tonumber(ARGV[2]) then return 0 end
redis.call("zadd", KEYS[1], ARGV[3], ARGV[4])
redis.call("expire", KEYS[1], ARGV[5])
return 1
"""


class ModelBusy(RuntimeError):
    """No background slot for the model became free in time."""


def max_background_per_model(path: Path | None = None) -> int | None:
    """``[model_limits].max_background_per_model``; None (absent) means no limit."""
    value = section("model_limits", path).get("max_background_per_model")
    if value is not None and (isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 1024):
        raise DeploymentConfigError(f"{_FILE} [model_limits].max_background_per_model must be an integer from 1 to 1024")
    return value


class ModelLimiter:
    """Per-model slots for background calls."""

    def __init__(self, limit: int | None, redis_client=None, prefix: str = "nexus") -> None:
        self.limit, self._redis, self._prefix = limit, redis_client, prefix
        self._local: dict[str, threading.BoundedSemaphore] = {}
        self._lock = threading.Lock()
        self._script = redis_client.register_script(_ACQUIRE) if redis_client is not None else None

    def _semaphore(self, key: str) -> threading.BoundedSemaphore:
        with self._lock:
            return self._local.setdefault(key, threading.BoundedSemaphore(self.limit))

    @contextlib.contextmanager
    def slot(self, model_key: str) -> Iterator[None]:
        """Hold one background slot for ``model_key`` while the body runs; waits for a free one."""
        if self.limit is None:
            yield
            return
        deadline = time.monotonic() + MAX_WAIT_SECONDS
        local = self._semaphore(model_key)
        if not local.acquire(timeout=MAX_WAIT_SECONDS):
            raise ModelBusy("model busy")
        holder = secrets.token_hex(8)
        try:
            self._take_remote(model_key, holder, deadline)
            try:
                yield
            finally:
                self._release_remote(model_key, holder)
        finally:
            local.release()

    @contextlib.asynccontextmanager
    async def aslot(self, model_key: str) -> AsyncIterator[None]:
        """Async form: the wait runs in a thread so the event loop keeps serving other work."""
        if self.limit is None:
            yield
            return
        cm = self.slot(model_key)
        await asyncio.to_thread(cm.__enter__)
        try:
            yield
        finally:
            await asyncio.to_thread(cm.__exit__, None, None, None)

    def _take_remote(self, model_key: str, holder: str, deadline: float) -> None:
        if self._script is None:
            return
        key = f"{self._prefix}:model:{model_key}:background"
        while True:
            now = time.time()
            try:
                if self._script(keys=[key], args=[now, self.limit, now + LEASE_SECONDS, holder, LEASE_SECONDS]):
                    return
            except Exception:  # Redis trouble must not block jobs: this process's own cap still applies
                return
            if time.monotonic() >= deadline:
                raise ModelBusy("model busy")
            time.sleep(POLL_SECONDS)

    def _release_remote(self, model_key: str, holder: str) -> None:
        if self._script is None:
            return
        with contextlib.suppress(Exception):
            self._redis.zrem(f"{self._prefix}:model:{model_key}:background", holder)


_limiter: ModelLimiter | None = None
_guard = threading.Lock()


def background_limiter() -> ModelLimiter:
    """The process's limiter, built on first use from ``[model_limits]`` (and the Redis bus when installed)."""
    global _limiter
    with _guard:
        if _limiter is None:
            from nexus_platform.runs.bus import channels
            current = channels()
            client = getattr(current.bus, "_sync", None) if current is not None and current.bus.name == "redis" else None
            _limiter = ModelLimiter(max_background_per_model(), client, current.settings.prefix if current else "nexus")
        return _limiter


def reset_background_limiter() -> None:
    """Forget the cached limiter (tests, configuration reload)."""
    global _limiter
    with _guard:
        _limiter = None
