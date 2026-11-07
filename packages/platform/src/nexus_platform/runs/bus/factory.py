"""Process-wide access to the configured Run event channels.

``install_channels`` is called once at API and worker start-up (and by tests) with that process's
session factory. Code that publishes or signals asks ``channels()``; when nothing was installed the
answer is ``None`` and publishing quietly does nothing, which is also what the database backend does.
"""
from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from nexus_core.run_events import ControlChannel, LiveRunMarker, RunEventBus
from .config import RunEventSettings, run_event_settings

logger = logging.getLogger("nexus_platform.run_events")


@dataclass(frozen=True)
class Channels:
    """The bus, the control wake-up and the live-run marker of one process, with the settings that built them."""

    bus: RunEventBus
    control: ControlChannel
    marker: LiveRunMarker
    settings: RunEventSettings


_lock = threading.Lock()
_installed: Channels | None = None
#: One memory bus per process: the API and the embedded worker thread must share the same instance.


def build_channels(factory: Callable[[], Any], settings: RunEventSettings | None = None) -> Channels:
    """Construct the channels for ``settings`` (read from ``configs/nexus.toml`` when omitted)."""
    settings = settings or run_event_settings()
    if settings.backend == "redis":
        from .control import RedisControl, RedisMarker
        from .redis_backend import RedisBus
        return Channels(
            RedisBus(settings.redis_url, prefix=settings.prefix, maxlen=settings.maxlen,
                     retention_seconds=settings.retention_seconds),
            RedisControl(settings.redis_url, prefix=settings.prefix),
            RedisMarker(settings.redis_url, prefix=settings.prefix), settings)
    if settings.backend == "memory":
        from .memory import MemoryBus, MemoryControl, MemoryMarker
        return Channels(MemoryBus(maxlen=settings.maxlen, retention_seconds=settings.retention_seconds),
                        MemoryControl(), MemoryMarker(), settings)
    from .control import DatabaseControl, DatabaseMarker
    from .database import DatabaseBus
    return Channels(DatabaseBus(factory, poll_min_ms=settings.poll_min_ms, poll_max_ms=settings.poll_max_ms),
                    DatabaseControl(), DatabaseMarker(factory), settings)


def install_channels(factory: Callable[[], Any], settings: RunEventSettings | None = None) -> Channels:
    """Install this process's channels once; later calls return the installed ones."""
    global _installed
    with _lock:
        if _installed is None:
            _installed = build_channels(factory, settings)
            logger.info("Run event channel ready", extra={"backend": _installed.bus.name})
        return _installed


def channels() -> Channels | None:
    """The installed channels, or None before ``install_channels``."""
    return _installed


def reset_channels() -> None:
    """Forget and close the installed channels (tests and orderly shutdown)."""
    global _installed
    with _lock:
        current, _installed = _installed, None
    if current is not None:
        current.bus.close()
