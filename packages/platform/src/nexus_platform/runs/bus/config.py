"""``[run_events]`` and ``[deployment]`` settings for the Run event channel.

Read from ``configs/nexus.toml`` like every other operator setting. An invalid value raises
DeploymentConfigError so a typo stops the process instead of silently changing behaviour.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from nexus_core.deployment import CONFIG_RELATIVE_PATH, DeploymentConfigError, section

_FILE = CONFIG_RELATIVE_PATH.as_posix()
BACKENDS = ("database", "redis", "memory")
MODES = ("split", "embedded")


@dataclass(frozen=True)
class DeploymentSettings:
    """``[deployment]``: how API and worker are started."""

    mode: str = "split"
    #: Concurrent background jobs (index, consolidation, embedding) while embedded in the API process.
    background_concurrency: int = 1
    #: Worker threads in the API process when embedded. One worker executes one Run at a time, so this is
    #: also how many Runs can execute at once.
    embedded_workers: int = 4


@dataclass(frozen=True)
class RunEventSettings:
    """``[run_events]``: the live event channel."""

    backend: str = "database"
    redis_url: str = "redis://localhost:6379/0"
    prefix: str = "nexus"
    #: Events kept per Run on the bus (memory deque size / Redis Stream MAXLEN).
    maxlen: int = 4096
    #: Seconds a finished Run's stream stays readable so late or reconnecting viewers can drain it.
    retention_seconds: int = 300
    #: Idle seconds between SSE heartbeats.
    heartbeat_seconds: float = 15.0
    #: Database backend: poll interval bounds in milliseconds; it backs off while a Run is quiet.
    poll_min_ms: int = 250
    poll_max_ms: int = 1000
    #: Seconds between a worker's database lease/cancel checks. With a bus that wakes the worker on cancel
    #: the check is only a safety net, so it is looser.
    lease_check_seconds: float = 1.0
    #: Seconds the live-run marker lives without being touched.
    live_ttl_seconds: int = 120


def _int(table: dict, key: str, default: int, low: int, high: int) -> int:
    value = table.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise DeploymentConfigError(f"{_FILE} [run_events].{key} must be an integer from {low} to {high}")
    return value


def _number(table: dict, key: str, default: float, low: float, high: float) -> float:
    value = table.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= value <= high:
        raise DeploymentConfigError(f"{_FILE} [run_events].{key} must be a number from {low:g} to {high:g}")
    return float(value)


def deployment_settings(path: Path | None = None) -> DeploymentSettings:
    """Read ``[deployment]``; absent means ``split`` with the defaults."""
    table = section("deployment", path)
    mode = table.get("mode", "split")
    if mode not in MODES:
        raise DeploymentConfigError(f"{_FILE} [deployment].mode must be one of {', '.join(MODES)}")
    concurrency = table.get("background_concurrency", 1)
    if isinstance(concurrency, bool) or not isinstance(concurrency, int) or not 1 <= concurrency <= 16:
        raise DeploymentConfigError(f"{_FILE} [deployment].background_concurrency must be an integer from 1 to 16")
    workers = table.get("embedded_workers", 4)
    if isinstance(workers, bool) or not isinstance(workers, int) or not 1 <= workers <= 32:
        raise DeploymentConfigError(f"{_FILE} [deployment].embedded_workers must be an integer from 1 to 32")
    return DeploymentSettings(mode=mode, background_concurrency=concurrency, embedded_workers=workers)


def run_event_settings(path: Path | None = None) -> RunEventSettings:
    """Read ``[run_events]``.

    The backend defaults to ``database`` (no extra service). Embedded mode defaults to ``memory`` because
    the worker shares the API process; naming ``database`` or ``redis`` there is still allowed. The memory
    backend in split mode is refused: a worker process cannot hand events to another process through it.
    """
    table = section("run_events", path)
    deployment = deployment_settings(path)
    backend = table.get("backend", "memory" if deployment.mode == "embedded" else "database")
    if backend not in BACKENDS:
        raise DeploymentConfigError(f"{_FILE} [run_events].backend must be one of {', '.join(BACKENDS)}")
    if backend == "memory" and deployment.mode == "split":
        raise DeploymentConfigError(
            f"{_FILE} [run_events].backend = \"memory\" needs [deployment].mode = \"embedded\": "
            "with separate API and worker processes, events published by the worker never reach the API")
    url = table.get("redis_url", RunEventSettings.redis_url)
    prefix = table.get("prefix", RunEventSettings.prefix)
    if not isinstance(url, str) or not url.startswith(("redis://", "rediss://", "unix://")):
        raise DeploymentConfigError(f"{_FILE} [run_events].redis_url must be a redis:// or rediss:// URL")
    if not isinstance(prefix, str) or not prefix or len(prefix) > 40 or not prefix.replace("-", "").replace("_", "").isalnum():
        raise DeploymentConfigError(f"{_FILE} [run_events].prefix must be 1 to 40 letters, digits, '-' or '_'")
    poll_min = _int(table, "poll_min_ms", 250, 50, 5000)
    poll_max = _int(table, "poll_max_ms", 1000, 50, 30000)
    if poll_max < poll_min:
        raise DeploymentConfigError(f"{_FILE} [run_events].poll_max_ms cannot be less than poll_min_ms")
    # A bus that wakes the worker on cancel makes the database check a safety net, so it can be looser.
    default_check = 1.0 if backend == "database" else 5.0
    return RunEventSettings(
        backend=backend, redis_url=url, prefix=prefix,
        maxlen=_int(table, "maxlen", 4096, 64, 1_000_000),
        retention_seconds=_int(table, "retention_seconds", 300, 0, 86400),
        heartbeat_seconds=_number(table, "heartbeat_seconds", 15.0, 1.0, 3600.0),
        poll_min_ms=poll_min, poll_max_ms=poll_max,
        lease_check_seconds=_number(table, "lease_check_seconds", default_check, 0.2, 30.0),
        live_ttl_seconds=_int(table, "live_ttl_seconds", 120, 10, 3600))
