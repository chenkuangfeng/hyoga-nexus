"""Database bus: no extra service, the database is also the channel.

Durable events are read back from ``run_events``; the bus itself holds nothing, so ``message.delta``
stays a durable event on this backend. What changes against polling per connection is that one
poller per Run in this process serves every subscriber of that Run, and that it backs off while the
Run is quiet. Publishing is a no-op because the commit already made the event visible.
"""
from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import AsyncIterator, Callable
from datetime import timezone
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import select

from nexus_core.run_events import END, HEARTBEAT, BusEvent, BusItem, ProducerLease
from nexus_platform.persistence.models import RunEventRecord

logger = logging.getLogger("nexus_platform.run_events")
READ_LIMIT = 500


def _to_event(row: RunEventRecord) -> BusEvent:
    at = row.occurred_at
    if at is not None and at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    return BusEvent(str(row.run_id), row.event_type, row.payload or {}, row.sequence, at.isoformat() if at else None,
                    str(row.sequence))


class _Poller:
    """Reads one Run's new events and fans them out to every subscriber of this process."""

    def __init__(self, bus: "DatabaseBus", run_id: UUID) -> None:
        self.bus, self.run_id = bus, run_id
        self.cursor = 0
        self.queues: list[asyncio.Queue] = []
        self.task: asyncio.Task | None = None

    async def run(self) -> None:
        delay = self.bus.poll_min
        while self.queues:
            rows = await asyncio.to_thread(self.bus.read, self.run_id, self.cursor)
            if rows:
                delay = self.bus.poll_min
                for row in rows:
                    event = _to_event(row)
                    self.cursor = row.sequence
                    for queue in list(self.queues):
                        queue.put_nowait(event)
                if len(rows) == READ_LIMIT:
                    continue
            else:
                delay = min(self.bus.poll_max, delay * 1.5)
            await asyncio.sleep(delay)


class DatabaseBus:
    """Shared poller over ``run_events``."""

    name = "database"
    supports_ephemeral = False
    cross_process = True

    def __init__(self, factory: Callable[[], Any], *, poll_min_ms: int = 250, poll_max_ms: int = 1000) -> None:
        self._factory = factory
        self.poll_min, self.poll_max = poll_min_ms / 1000, poll_max_ms / 1000
        self._pollers: dict[tuple[int, UUID], _Poller] = {}
        self._lock = threading.Lock()

    def read(self, run_id: UUID, after: int) -> list[RunEventRecord]:
        with self._factory() as db:
            return list(db.scalars(select(RunEventRecord).where(
                RunEventRecord.run_id == run_id, RunEventRecord.sequence > after)
                .order_by(RunEventRecord.sequence).limit(READ_LIMIT)))

    # The commit already published the event to every reader; nothing to do on the producer side.
    def publish(self, event: BusEvent) -> None:
        return None

    def publish_end(self, run_id: UUID | str) -> None:
        return None

    def tail(self, run_id: UUID | str) -> str | None:
        return None

    def cleanup(self, run_id: UUID | str) -> None:
        return None

    def ping(self) -> bool:
        return True

    def close(self) -> None:
        return None

    def start_producer(self, run_id: UUID | str, owner: str) -> ProducerLease | None:
        return None

    def renew_producer(self, lease: ProducerLease) -> bool:
        return True

    def finish_producer(self, lease: ProducerLease) -> None:
        return None

    def producer_state(self, run_id: UUID | str) -> Literal["untracked", "active", "expired"]:
        return "untracked"

    async def subscribe(self, run_id: UUID | str, *, after: str | None, heartbeat: float) -> AsyncIterator[BusItem]:
        """Durable events after ``after``. The caller ends the stream when the Run stops or waits."""
        rid = run_id if isinstance(run_id, UUID) else UUID(str(run_id))
        try:
            start = int(after) if after else 0
        except ValueError:
            start = 0
        loop = asyncio.get_running_loop()
        key = (id(loop), rid)
        queue: asyncio.Queue = asyncio.Queue()
        with self._lock:
            poller = self._pollers.get(key)
            if poller is None:
                poller = self._pollers[key] = _Poller(self, rid)
                poller.cursor = start
            elif start < poller.cursor:
                # A late joiner behind the shared cursor reads its own backlog first.
                for row in await asyncio.to_thread(self.read, rid, start):
                    if row.sequence <= poller.cursor:
                        queue.put_nowait(_to_event(row))
            poller.queues.append(queue)
            if poller.task is None or poller.task.done():
                poller.task = loop.create_task(poller.run())
        try:
            while True:
                try:
                    yield await asyncio.wait_for(queue.get(), timeout=heartbeat)
                except asyncio.TimeoutError:
                    yield HEARTBEAT
        finally:
            with self._lock:
                if queue in poller.queues:
                    poller.queues.remove(queue)
                if not poller.queues:
                    self._pollers.pop(key, None)
                    if poller.task is not None:
                        poller.task.cancel()
