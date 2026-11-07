"""``[worker]`` and ``[api]`` concurrency settings (openspec 2026-11-07-worker-concurrency).

``[worker]`` sizes one worker process: how many Runs it executes at once and how many threads it uses for
synchronous database calls. ``[api]`` sizes the thread pool that serves synchronous endpoints, and with it the
API's database connection pool. An invalid value raises DeploymentConfigError so a typo stops start-up.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from nexus_core.deployment import CONFIG_RELATIVE_PATH, DeploymentConfigError, section

_FILE = CONFIG_RELATIVE_PATH.as_posix()
#: A SQLite database has one writer; more concurrent Runs only wait on its lock.
SQLITE_MAX_CONCURRENT_RUNS = 4
#: Connections kept beyond the threads that use them: lease checks, the claim loop, background jobs.
POOL_HEADROOM = 4


@dataclass(frozen=True)
class WorkerSettings:
    """``[worker]``: one worker process."""

    max_concurrent_runs: int = 32
    #: Threads for synchronous database calls. A Run mostly waits on the model, so this is far below the run count.
    db_threads: int = 16
    #: Seconds to wait for Runs to wind down on stop before leaving them to lease recovery.
    stop_timeout_seconds: float = 30.0

    @property
    def pool_size(self) -> int:
        """Database connections the worker's engine keeps: one per database thread, plus headroom."""
        return self.db_threads + POOL_HEADROOM

    def effective_runs(self, database_url: str) -> int:
        """Concurrent Runs actually allowed: SQLite is capped because it has a single writer."""
        if database_url.startswith("sqlite"):
            return min(self.max_concurrent_runs, SQLITE_MAX_CONCURRENT_RUNS)
        return self.max_concurrent_runs


@dataclass(frozen=True)
class ApiSettings:
    """``[api]``: threads serving synchronous endpoints, and the database connections behind them."""

    threads: int = 40

    @property
    def pool_size(self) -> int:
        return self.threads + POOL_HEADROOM


def _int(table: dict, name: str, key: str, default: int, low: int, high: int) -> int:
    value = table.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise DeploymentConfigError(f"{_FILE} [{name}].{key} must be an integer from {low} to {high}")
    return value


def worker_settings(path: Path | None = None) -> WorkerSettings:
    """Read ``[worker]``; absent keys take the defaults."""
    table = section("worker", path)
    stop = table.get("stop_timeout_seconds", 30.0)
    if isinstance(stop, bool) or not isinstance(stop, (int, float)) or not 1 <= stop <= 3600:
        raise DeploymentConfigError(f"{_FILE} [worker].stop_timeout_seconds must be a number from 1 to 3600")
    return WorkerSettings(
        max_concurrent_runs=_int(table, "worker", "max_concurrent_runs", 32, 1, 1024),
        db_threads=_int(table, "worker", "db_threads", 16, 1, 512),
        stop_timeout_seconds=float(stop))


def api_settings(path: Path | None = None) -> ApiSettings:
    """Read ``[api]``; absent keys take the defaults."""
    return ApiSettings(threads=_int(section("api", path), "api", "threads", 40, 1, 512))
