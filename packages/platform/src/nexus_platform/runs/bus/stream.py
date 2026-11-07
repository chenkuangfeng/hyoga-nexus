"""Subscription pipeline behind ``GET /runs/{id}/events``: database replay, then the live bus.

The caller supplies two small synchronous functions (each opens its own short session and checks
authorization), so a stream holds no database connection while it waits.

Order of work, which is what makes the hand-over lossless:

1. Replay durable events after the client's cursor from the database.
2. Read the bus from the start of what it still retains. Durable events at or below the cursor are
   dropped; a durable event that skips ahead triggers a catch-up read from the database, which also
   heals events the bus never received. Ephemeral text of a turn the database already completed is
   dropped, because ``message.completed`` carries that turn's full text.
3. On a gap, an end marker or a stopped producer, read the database again before finishing.

A resumed connection (cursor above zero) starts with ``resync``: unsequenced text the client holds
from before the break is replayed from the bus, so the client must drop its copy first.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from nexus_core.run_events import BusEvent, BusUnavailable, End, Heartbeat, StreamGap
from .factory import Channels

logger = logging.getLogger("nexus_platform.run_events")
#: Statuses after which the stream is finished: the Run ended or stopped to wait for the user.
ENDED_STATUSES = frozenset({"completed", "failed", "cancelled", "interrupted", "waiting_input", "waiting_approval"})
PAGE_LIMIT = 200
#: Seconds between status/authorization checks while no event arrives.
CHECK_SECONDS_DATABASE = 1.0
CHECK_SECONDS_BUS = 5.0

Page = Callable[[int, int], tuple[list[BusEvent], str]]


@dataclass(frozen=True)
class StreamItem:
    """What the endpoint renders: an event, a resync request, a heartbeat or the end of the stream."""

    kind: Literal["event", "resync", "heartbeat", "closed"]
    event: BusEvent | None = None
    #: Highest durable sequence delivered so far; an unsequenced event reports it as its position.
    cursor: int = 0


async def stream_run_events(ch: Channels, run_id: UUID, after_sequence: int, page: Page,
                            status: Callable[[], str]) -> AsyncIterator[StreamItem]:
    """Yield ``StreamItem`` until the Run ends or waits; raises nothing for an unreachable bus (falls back to the database)."""
    bus = ch.bus
    heartbeat = ch.settings.heartbeat_seconds
    last = after_sequence
    completed_turns: set[int] = set()

    def note(event: BusEvent) -> None:
        if event.kind == "message.completed" and isinstance(event.payload.get("turn"), int):
            completed_turns.add(event.payload["turn"])

    async def catch_up() -> AsyncIterator[BusEvent]:
        """Durable events after ``last`` straight from the database."""
        nonlocal last
        while True:
            events, _ = await asyncio.to_thread(page, last, PAGE_LIMIT)
            for event in events:
                last = event.sequence or last
                note(event)
                yield event
            if len(events) < PAGE_LIMIT:
                return

    try:
        if after_sequence > 0 and bus.supports_ephemeral:
            yield StreamItem("resync", None, last)
        async for event in catch_up():
            yield StreamItem("event", event, last)
        if await asyncio.to_thread(status) in ENDED_STATUSES:
            return
        iterator = bus.subscribe(run_id, after=str(last) if not bus.supports_ephemeral else None, heartbeat=heartbeat)
        check = CHECK_SECONDS_BUS if bus.supports_ephemeral else CHECK_SECONDS_DATABASE
        pending: asyncio.Future | None = None
        try:
            while True:
                if pending is None:
                    pending = asyncio.ensure_future(iterator.__anext__())
                done, _ = await asyncio.wait({pending}, timeout=check)
                if not done:
                    # Quiet period: confirm the viewer may still see the Run and that it is still going.
                    if await asyncio.to_thread(status) in ENDED_STATUSES:
                        async for event in catch_up():
                            yield StreamItem("event", event, last)
                        return
                    if bus.supports_ephemeral and bus.producer_state(run_id) == "expired":
                        yield StreamItem("closed")
                        return
                    continue
                try:
                    item = pending.result()
                except StopAsyncIteration:
                    return
                finally:
                    pending = None
                if isinstance(item, Heartbeat):
                    yield StreamItem("heartbeat")
                elif isinstance(item, StreamGap):
                    yield StreamItem("resync", None, last)
                    async for event in catch_up():
                        yield StreamItem("event", event, last)
                elif isinstance(item, End):
                    async for event in catch_up():
                        yield StreamItem("event", event, last)
                    return
                elif item.sequence is None:
                    turn = item.payload.get("turn")
                    if turn not in completed_turns:
                        yield StreamItem("event", item, last)
                elif item.sequence > last:
                    if item.sequence == last + 1:
                        last = item.sequence
                        note(item)
                        yield StreamItem("event", item, last)
                    else:
                        # Events between were never published to the bus: read them from the database.
                        async for event in catch_up():
                            yield StreamItem("event", event, last)
        finally:
            if pending is not None and not pending.done():
                pending.cancel()
            await _close(iterator)
    except BusUnavailable:
        logger.warning("Run event bus unavailable while streaming", extra={"run_id": str(run_id)})
        yield StreamItem("resync", None, last)
        # Fall back to reading the database until the Run stops: the same answer, just slower.
        while True:
            async for event in catch_up():
                yield StreamItem("event", event, last)
            if await asyncio.to_thread(status) in ENDED_STATUSES:
                async for event in catch_up():
                    yield StreamItem("event", event, last)
                return
            yield StreamItem("heartbeat")
            await asyncio.sleep(CHECK_SECONDS_DATABASE)
    except Exception:
        logger.info("Run stream closed", extra={"run_id": str(run_id)}, exc_info=True)
        yield StreamItem("closed")


async def _close(iterator: AsyncIterator) -> None:
    close = getattr(iterator, "aclose", None)
    if close is not None:
        try:
            await close()
        except Exception:  # closing must never mask the stream's own outcome
            pass
