"""Control wake-up and live-run marker for the Redis and database backends (memory ones live in ``memory.py``)."""
from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any
from uuid import UUID

from sqlalchemy import select

from nexus_platform.persistence.models import RunRecord

logger = logging.getLogger("nexus_platform.run_events")
#: Longest single blocking wait; keeps a thread's socket timeout above the wait.
MAX_WAIT_SECONDS = 2.0


class DatabaseControl:
    """No side channel: ``wait`` just paces the caller's database check, so cancel latency is the check interval."""

    def signal(self, run_id: UUID | str, kind: str) -> None:
        return None

    def wait(self, run_id: UUID | str, timeout: float) -> bool:
        time.sleep(max(0.0, timeout))
        return False


class DatabaseMarker:
    """The live Run of a session is the one the database says is running, so nothing is stored."""

    def __init__(self, factory: Callable[[], Any]) -> None:
        self._factory = factory

    def claim(self, session_id: UUID | str, run_id: UUID | str, ttl: float) -> None:
        return None

    touch = claim

    def get(self, session_id: UUID | str) -> str | None:
        with self._factory() as db:
            run_id = db.scalar(select(RunRecord.id).where(RunRecord.session_id == UUID(str(session_id)),
                                                          RunRecord.status == "running"))
            return str(run_id) if run_id else None

    def clear(self, session_id: UUID | str, run_id: UUID | str) -> None:
        return None


class RedisControl:
    """Cancel wake-up on a list key apart from the event stream, so control never shows up in a viewer's feed."""

    def __init__(self, url: str, *, prefix: str, client: Any = None, ttl: int = 3600) -> None:
        import redis
        # A blocking pop outlasts the producer client's short socket timeout, hence a client of its own.
        self._client = client or redis.Redis.from_url(url, socket_timeout=MAX_WAIT_SECONDS + 3,
                                                      socket_connect_timeout=1.0)
        self.prefix, self.ttl = prefix, ttl

    def key(self, run_id: UUID | str) -> str:
        return f"{self.prefix}:run:{run_id}:control"

    def signal(self, run_id: UUID | str, kind: str) -> None:
        try:
            key = self.key(run_id)
            self._client.lpush(key, kind)
            self._client.expire(key, self.ttl)
        except Exception:  # a lost signal only delays the cancel to the next database check
            logger.warning("Control signal failed", extra={"run_id": str(run_id)}, exc_info=True)

    def wait(self, run_id: UUID | str, timeout: float) -> bool:
        try:
            got = self._client.blpop(self.key(run_id), timeout=min(max(timeout, 0.05), MAX_WAIT_SECONDS))
        except Exception:
            time.sleep(min(max(timeout, 0.05), MAX_WAIT_SECONDS))
            return False
        if got:
            try:
                self._client.delete(self.key(run_id))  # collapse repeated signals into one wake-up
            except Exception:
                pass
        return bool(got)


_COMPARE_DELETE = """
if redis.call("get", KEYS[1]) == ARGV[1] then return redis.call("del", KEYS[1]) end
return 0
"""


class RedisMarker:
    """``{prefix}:session:{id}:live`` holds the generating Run id and expires unless touched."""

    def __init__(self, url: str, *, prefix: str, client: Any = None) -> None:
        import redis
        self._client = client or redis.Redis.from_url(url, socket_timeout=0.5, socket_connect_timeout=0.5)
        self.prefix = prefix
        self._delete = self._client.register_script(_COMPARE_DELETE)

    def key(self, session_id: UUID | str) -> str:
        return f"{self.prefix}:session:{session_id}:live"

    def claim(self, session_id: UUID | str, run_id: UUID | str, ttl: float) -> None:
        try:
            self._client.set(self.key(session_id), str(run_id), ex=max(1, int(ttl)))
        except Exception:
            logger.warning("Live-run marker write failed", extra={"session_id": str(session_id)}, exc_info=True)

    touch = claim

    def get(self, session_id: UUID | str) -> str | None:
        try:
            value = self._client.get(self.key(session_id))
        except Exception:
            return None
        return value.decode() if isinstance(value, bytes) else value

    def clear(self, session_id: UUID | str, run_id: UUID | str) -> None:
        try:
            self._delete(keys=[self.key(session_id)], args=[str(run_id)])
        except Exception:
            logger.warning("Live-run marker clear failed", extra={"session_id": str(session_id)}, exc_info=True)
