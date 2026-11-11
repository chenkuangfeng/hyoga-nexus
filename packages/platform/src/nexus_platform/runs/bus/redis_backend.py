"""Redis Streams bus: the production backend for split deployments.

Layout follows deer-flow's ``RedisStreamBridge``: one Stream per Run (``XADD MAXLEN ~``), blocking
``XREAD`` for subscribers, a gap when the cursor fell out of the retained window, and a producer
lease that fences ephemeral publishing with a compare-then-write Lua script. WeKnora contributes the
control key (kept off the user-visible stream) and the live-run marker.

Publishing uses the synchronous client because events are produced from commit hooks and worker
threads; subscribing uses the asynchronous client on the API loop. A circuit breaker stops a dead
Redis from stalling the producer: after a failure publishing is skipped for ``BREAKER_SECONDS``.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import secrets
import threading
import time
from collections.abc import AsyncIterator
from typing import Any, Literal
from uuid import UUID

from nexus_core.run_events import (END, HEARTBEAT, BusEvent, BusItem, BusUnavailable, ProducerLease, StreamGap)

try:
    import redis
    import redis.asyncio as aredis
    from redis.exceptions import RedisError
except ImportError:  # pragma: no cover - the extra is optional
    raise ImportError("[run_events].backend = \"redis\" needs the redis package: uv sync --extra redis") from None

logger = logging.getLogger("nexus_platform.run_events")

PRODUCER_LEASE_SECONDS = 30
BREAKER_SECONDS = 5.0
SOCKET_TIMEOUT = 0.5
_STREAM_ID = re.compile(r"[0-9]+(-[0-9]+)?")
_XREAD_COUNT = 64
#: Events one subscriber may leave unread before it is cut off (a viewer whose connection stalled).
_SUBSCRIBER_BACKLOG = 2048
_MAX_RETRIES = 3

#: XADD only while the caller still holds the producer token.
_FENCED_XADD = """
if redis.call("get", KEYS[1]) ~= ARGV[1] then return false end
return redis.call("xadd", KEYS[2], "MAXLEN", "~", ARGV[2], "*",
  "kind", ARGV[3], "event", ARGV[4], "seq", ARGV[5], "at", ARGV[6], "data", ARGV[7])
"""
_RENEW = """
if redis.call("get", KEYS[1]) ~= ARGV[1] then return 0 end
redis.call("expire", KEYS[1], ARGV[2])
return 1
"""
_DELETE_IF = """
if redis.call("get", KEYS[1]) == ARGV[1] then return redis.call("del", KEYS[1]) end
return 0
"""


def _text(value: Any) -> str:
    return value.decode() if isinstance(value, bytes) else str(value)


class _Reader:
    """One blocking ``XREAD`` per (event loop, Run), fanned out to every subscriber of this process.

    Without it each viewer of a Run would hold its own Redis connection in a blocking read, so a hundred viewers
    cost a hundred connections and a hundred decodes of every event. The reader stops when its last subscriber
    leaves or the Run's end marker has been delivered.
    """

    def __init__(self, bus: "RedisBus", run_id: str, key: str, cursor: str, heartbeat: float) -> None:
        self.bus, self.run_id, self.key, self.cursor, self.heartbeat = bus, run_id, key, cursor, heartbeat
        self.queues: list[asyncio.Queue] = []
        self.task: asyncio.Task | None = None

    def push(self, item: Any) -> None:
        """Hand `item` to every subscriber. One that has fallen `_SUBSCRIBER_BACKLOG` events behind is dropped from the
        reader and told the bus is unavailable to it, which makes the stream pipeline continue from the database: a
        stalled viewer must neither grow memory without bound nor slow the others."""
        for queue in list(self.queues):
            if queue.full():
                self.queues.remove(queue)
                while not queue.empty():
                    queue.get_nowait()
                queue.put_nowait(BusUnavailable("subscriber too slow for the live channel"))
                logger.warning("Dropped a slow subscriber of a Run stream", extra={"run_id": self.run_id})
                continue
            queue.put_nowait(item)

    async def run(self) -> None:
        client, failures = self.bus._client(), 0
        while self.queues:
            try:
                response = await client.xread({self.key: self.cursor}, count=_XREAD_COUNT,
                                              block=max(1, int(self.heartbeat * 1000)))
                failures = 0
            except RedisError as exc:
                failures += 1
                if failures > _MAX_RETRIES:
                    self.push(BusUnavailable(f"redis bus unavailable: {type(exc).__name__}"))
                    return
                await asyncio.sleep(min(self.heartbeat, 0.2 * 2 ** failures))
                continue
            if not response:
                self.push(HEARTBEAT)
                continue
            for _stream, entries in response:
                for entry_id, fields in entries:
                    self.cursor = _text(entry_id)
                    item = self.bus._to_event(self.run_id, self.cursor, fields)
                    self.push(item)
                    if item is END:
                        return


class RedisBus:
    """Run events on Redis Streams."""

    name = "redis"
    supports_ephemeral = True
    cross_process = True

    def __init__(self, url: str, *, prefix: str = "nexus", maxlen: int = 4096, retention_seconds: int = 300,
                 sync_client: Any = None, async_client_factory: Any = None) -> None:
        self.prefix, self.maxlen, self.retention = prefix, maxlen, retention_seconds
        self._url = url
        self._sync = sync_client or redis.Redis.from_url(url, socket_timeout=SOCKET_TIMEOUT,
                                                         socket_connect_timeout=SOCKET_TIMEOUT)
        self._async_factory = async_client_factory or (lambda: aredis.Redis.from_url(url))
        self._async_clients: dict[int, Any] = {}
        self._readers: dict[tuple[int, str], _Reader] = {}
        self._fenced_xadd = self._sync.register_script(_FENCED_XADD)
        self._renew = self._sync.register_script(_RENEW)
        self._delete_if = self._sync.register_script(_DELETE_IF)
        self._tokens: dict[str, str] = {}
        self._broken_until = 0.0
        self._lock = threading.Lock()

    # -- keys ----------------------------------------------------------------------------------

    def stream_key(self, run_id: UUID | str) -> str:
        return f"{self.prefix}:run:{run_id}:events"

    def producer_key(self, run_id: UUID | str) -> str:
        return f"{self.prefix}:run:{run_id}:producer"

    # -- producer side -------------------------------------------------------------------------

    def _guard(self) -> None:
        if time.monotonic() < self._broken_until:
            raise BusUnavailable("redis bus is in back-off after a failure")

    def _failed(self, exc: Exception) -> BusUnavailable:
        self._broken_until = time.monotonic() + BREAKER_SECONDS
        return BusUnavailable(f"redis bus unavailable: {type(exc).__name__}")

    def _encode(self, event: BusEvent) -> tuple:
        return (event.kind, event.kind, "" if event.sequence is None else str(event.sequence),
                event.occurred_at or "", json.dumps(event.payload, default=str, separators=(",", ":")))

    def publish(self, event: BusEvent) -> None:
        self._guard()
        kind, name, seq, at, data = self._encode(event)
        try:
            token = self._tokens.get(event.run_id)
            if token is not None and event.sequence is None:
                # Ephemeral text is fenced: a worker whose lease was taken over must not keep streaming.
                added = self._fenced_xadd(keys=[self.producer_key(event.run_id), self.stream_key(event.run_id)],
                                          args=[token, self.maxlen, "event", name, seq, at, data])
                if not added:
                    raise BusUnavailable("producer lease lost")
            else:
                self._sync.xadd(self.stream_key(event.run_id),
                                {"kind": "event", "event": name, "seq": seq, "at": at, "data": data},
                                maxlen=self.maxlen, approximate=True)
        except BusUnavailable:
            raise
        except RedisError as exc:
            raise self._failed(exc) from exc

    def publish_end(self, run_id: UUID | str) -> None:
        self._guard()
        key = self.stream_key(run_id)
        try:
            self._sync.xadd(key, {"kind": "end", "event": "", "seq": "", "at": "", "data": "null"},
                            maxlen=self.maxlen, approximate=True)
            # The stream outlives the Run so a reconnecting viewer can drain it, then Redis drops it.
            self._sync.expire(key, max(1, self.retention))
        except RedisError as exc:
            raise self._failed(exc) from exc

    def tail(self, run_id: UUID | str) -> str | None:
        self._guard()
        try:
            entries = self._sync.xrevrange(self.stream_key(run_id), count=1)
        except RedisError as exc:
            raise self._failed(exc) from exc
        return _text(entries[0][0]) if entries else "0-0"

    def cleanup(self, run_id: UUID | str) -> None:
        try:
            self._sync.delete(self.stream_key(run_id), self.producer_key(run_id))
        except RedisError:
            logger.warning("Run stream cleanup failed", extra={"run_id": str(run_id)}, exc_info=True)
        self._tokens.pop(str(run_id), None)

    def ping(self) -> bool:
        try:
            return bool(self._sync.ping())
        except RedisError:
            return False

    def close(self) -> None:
        try:
            self._sync.close()
        except RedisError:
            pass
        self._async_clients.clear()

    # -- producer lease ------------------------------------------------------------------------

    def start_producer(self, run_id: UUID | str, owner: str) -> ProducerLease | None:
        key, token = self.producer_key(run_id), f"{owner}:{secrets.token_hex(6)}"
        try:
            # A new owner takes over unconditionally: the database lease already decided who may run.
            self._sync.set(key, token, ex=PRODUCER_LEASE_SECONDS)
        except RedisError as exc:
            raise self._failed(exc) from exc
        self._tokens[str(run_id)] = token
        return ProducerLease(str(run_id), token)

    def renew_producer(self, lease: ProducerLease) -> bool:
        try:
            return bool(self._renew(keys=[self.producer_key(lease.run_id)], args=[lease.token, PRODUCER_LEASE_SECONDS]))
        except RedisError as exc:
            raise self._failed(exc) from exc

    def finish_producer(self, lease: ProducerLease) -> None:
        self._tokens.pop(lease.run_id, None)
        try:
            self._delete_if(keys=[self.producer_key(lease.run_id)], args=[lease.token])
        except RedisError:
            logger.warning("Producer lease release failed", extra={"run_id": lease.run_id}, exc_info=True)

    def producer_state(self, run_id: UUID | str) -> Literal["untracked", "active", "expired"]:
        try:
            if self._sync.exists(self.producer_key(run_id)):
                return "active"
            # The stream exists without a live lease: the producer started and then went away.
            return "expired" if self._sync.exists(self.stream_key(run_id)) else "untracked"
        except RedisError:
            return "untracked"

    # -- consumer side -------------------------------------------------------------------------

    def _client(self) -> Any:
        """One asynchronous client per event loop (a client is bound to the loop it first runs on)."""
        loop_id = id(asyncio.get_running_loop())
        client = self._async_clients.get(loop_id)
        if client is None:
            client = self._async_clients[loop_id] = self._async_factory()
        return client

    @staticmethod
    def _id_lt(left: str, right: str) -> bool:
        def parts(value: str) -> tuple[int, int]:
            head, _, tail = value.partition("-")
            return int(head), int(tail or 0)
        return parts(left) < parts(right)

    def _to_event(self, run_id: str, entry_id: str, fields: dict) -> BusItem:
        f = {_text(k): _text(v) for k, v in fields.items()}
        if f.get("kind") == "end":
            return END
        try:
            payload = json.loads(f.get("data") or "{}")
        except ValueError:
            payload = {}
        seq = f.get("seq")
        return BusEvent(run_id, f.get("event", ""), payload if isinstance(payload, dict) else {},
                        int(seq) if seq else None, f.get("at") or None, entry_id)

    async def subscribe(self, run_id: UUID | str, *, after: str | None, heartbeat: float) -> AsyncIterator[BusItem]:
        key, rid = self.stream_key(run_id), str(run_id)
        client = self._client()
        cursor = after if after and _STREAM_ID.fullmatch(after) else "0-0"
        failures = 0
        if cursor != "0-0":
            # Only a resuming viewer can have fallen behind the retained window. A new one starts at the beginning, and
            # skipping this check for it keeps a burst of viewers from opening a connection each just to ask.
            try:
                first = await client.xrange(key, count=1)
            except RedisError as exc:
                raise BusUnavailable(f"redis bus unavailable: {type(exc).__name__}") from exc
            if first and self._id_lt(cursor, _text(first[0][0])):
                # The window moved past the cursor: events between were trimmed, so say so rather than skip silently.
                last = await client.xrevrange(key, count=1)
                yield StreamGap(cursor, _text(first[0][0]), _text(last[0][0]) if last else None)
        loop_id = id(asyncio.get_running_loop())
        queue: asyncio.Queue = asyncio.Queue(maxsize=_SUBSCRIBER_BACKLOG)
        reader = self._readers.get((loop_id, rid))
        if reader is None or reader.task is None or reader.task.done():
            reader = self._readers[(loop_id, rid)] = _Reader(self, rid, key, cursor, heartbeat)
            reader.queues.append(queue)
            reader.task = asyncio.get_running_loop().create_task(reader.run())
            floor = cursor
        else:
            # Joining a running reader: it is already past this subscriber's cursor, so the events in between are
            # read once from the stream, and live ones at or before that point are skipped as duplicates.
            floor = reader.cursor if self._id_lt(cursor, reader.cursor) else cursor
            reader.queues.append(queue)
            if floor != cursor:
                try:
                    backlog = await client.xrange(key, min=cursor, max=floor)
                except RedisError as exc:
                    self._leave(loop_id, rid, reader, queue)
                    raise BusUnavailable(f"redis bus unavailable: {type(exc).__name__}") from exc
                for entry_id, fields in backlog:
                    if not self._id_lt(cursor, _text(entry_id)):
                        continue
                    item = self._to_event(rid, _text(entry_id), fields)
                    yield item
                    if item is END:
                        self._leave(loop_id, rid, reader, queue)
                        return
        try:
            while True:
                item = await queue.get()
                if isinstance(item, Exception):
                    raise item
                if isinstance(item, BusEvent) and not self._id_lt(floor, item.cursor):
                    continue  # already delivered from the backlog
                yield item
                if item is END:
                    return
        finally:
            self._leave(loop_id, rid, reader, queue)

    def _leave(self, loop_id: int, rid: str, reader: _Reader, queue: asyncio.Queue) -> None:
        """Detach a subscriber; the last one out stops the reader."""
        if queue in reader.queues:
            reader.queues.remove(queue)
        if not reader.queues:
            if reader.task is not None and not reader.task.done():
                reader.task.cancel()
            if self._readers.get((loop_id, rid)) is reader:
                del self._readers[(loop_id, rid)]
