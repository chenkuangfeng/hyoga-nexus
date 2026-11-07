"""Synchronous database work off the event loop (openspec 2026-11-07-worker-concurrency).

The platform services use synchronous SQLAlchemy. With many Runs sharing one event loop, a database call made
on the loop would stall every Run for its duration, so coroutines hand such calls to a dedicated thread pool.

Until a worker configures the pool, calls share one thread: they never overlap, which keeps the behaviour that
tests (and a single in-memory SQLite connection) rely on.
"""
from __future__ import annotations

import asyncio
import contextvars
import functools
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, TypeVar

T = TypeVar("T")
_lock = threading.Lock()
_executor: ThreadPoolExecutor | None = None
_default: ThreadPoolExecutor | None = None


def configure_db_executor(max_workers: int) -> ThreadPoolExecutor:
    """Create the pool a worker process uses for database calls; call once, before Runs start."""
    global _executor
    with _lock:
        if _executor is not None:
            _executor.shutdown(wait=False)
        _executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="nexus-db")
        return _executor


def shutdown_db_executor() -> None:
    """Release the pool (orderly stop, tests)."""
    global _executor
    with _lock:
        pool, _executor = _executor, None
    if pool is not None:
        pool.shutdown(wait=True)


def db_executor() -> ThreadPoolExecutor:
    """The configured pool, or a single shared thread when none was configured."""
    global _default
    with _lock:
        if _executor is not None:
            return _executor
        if _default is None:
            _default = ThreadPoolExecutor(max_workers=1, thread_name_prefix="nexus-db-default")
        return _default


async def run_db(fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """Run a synchronous database function on the database pool and wait for it without blocking the loop."""
    context = contextvars.copy_context()
    return await asyncio.get_running_loop().run_in_executor(
        db_executor(), functools.partial(context.run, functools.partial(fn, *args, **kwargs)))


def offloaded(fn: Callable[..., T]) -> Callable[..., Any]:
    """Make a synchronous method awaitable: its body runs on the database pool.

    Meant for store methods whose whole body is a short database transaction. A method that also awaits
    something else must be split by hand.
    """
    @functools.wraps(fn)
    async def wrapper(self, *args, **kwargs):
        return await run_db(fn, self, *args, **kwargs)
    return wrapper
