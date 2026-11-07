"""In-process bus for the embedded deployment (API and worker in one process) and for tests.

Same shape as deer-flow's ``MemoryStreamBridge``: a bounded per-Run log plus wake-ups, so a
subscriber never polls. Publishing happens on worker threads and subscribing on the API event
loop, so a subscriber is woken with ``loop.call_soon_threadsafe``.
"""
from __future__ import annotations

import asyncio
import secrets
import threading
import time
from collections import deque
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Literal
from uuid import UUID

from nexus_core.run_events import END, HEARTBEAT, BusEvent, BusItem, End, ProducerLease, StreamGap

_END_KIND = "__end__"
#: Producer liveness: a lease not renewed for this long reads as expired.
PRODUCER_LEASE_SECONDS = 30.0


@dataclass
class _RunLog:
    entries: deque = field(default_factory=deque)  # (id:int, BusEvent | None for the end marker)
    next_id: int = 1
    ended_at: float | None = None
    waiters: list = field(default_factory=list)  # (loop, asyncio.Event)


class MemoryBus:
    """Bounded per-Run event log held in this process."""

    name = "memory"
    supports_ephemeral = True
    cross_process = False

    def __init__(self, *, maxlen: int = 4096, retention_seconds: float = 300.0) -> None:
        self.maxlen, self.retention = maxlen, retention_seconds
        self._runs: dict[str, _RunLog] = {}
        self._producers: dict[str, tuple[str, float]] = {}
        self._lock = threading.Lock()

    # -- producer side -------------------------------------------------------------------------

    def _log(self, run_id: str) -> _RunLog:
        log = self._runs.get(run_id)
        if log is None:
            log = self._runs[run_id] = _RunLog(entries=deque(maxlen=self.maxlen))
        return log

    def _purge(self, now: float) -> None:
        """Drop logs that ended longer ago than the retention; called under the lock."""
        for key in [k for k, log in self._runs.items() if log.ended_at is not None and now - log.ended_at > self.retention]:
            del self._runs[key]

    def _wake(self, log: _RunLog) -> None:
        for loop, flag in list(log.waiters):
            try:
                loop.call_soon_threadsafe(flag.set)
            except RuntimeError:  # the subscriber's loop is closed
                log.waiters.remove((loop, flag))

    def publish(self, event: BusEvent) -> None:
        with self._lock:
            self._purge(time.monotonic())
            log = self._log(event.run_id)
            log.entries.append((log.next_id, event))
            log.next_id += 1
            self._wake(log)

    def publish_end(self, run_id: UUID | str) -> None:
        with self._lock:
            log = self._log(str(run_id))
            log.entries.append((log.next_id, None))
            log.next_id += 1
            log.ended_at = time.monotonic()
            self._wake(log)

    def tail(self, run_id: UUID | str) -> str | None:
        with self._lock:
            log = self._runs.get(str(run_id))
            return str(log.next_id - 1) if log else "0"

    def cleanup(self, run_id: UUID | str) -> None:
        with self._lock:
            log = self._runs.pop(str(run_id), None)
            self._producers.pop(str(run_id), None)
            if log:
                self._wake(log)

    def ping(self) -> bool:
        return True

    def close(self) -> None:
        with self._lock:
            self._runs.clear()
            self._producers.clear()

    # -- producer lease ------------------------------------------------------------------------

    def start_producer(self, run_id: UUID | str, owner: str) -> ProducerLease | None:
        token = secrets.token_hex(8)
        with self._lock:
            self._producers[str(run_id)] = (token, time.monotonic() + PRODUCER_LEASE_SECONDS)
        return ProducerLease(str(run_id), token)

    def renew_producer(self, lease: ProducerLease) -> bool:
        with self._lock:
            held = self._producers.get(lease.run_id)
            if held is None or held[0] != lease.token:
                return False
            self._producers[lease.run_id] = (lease.token, time.monotonic() + PRODUCER_LEASE_SECONDS)
            return True

    def finish_producer(self, lease: ProducerLease) -> None:
        with self._lock:
            held = self._producers.get(lease.run_id)
            if held is not None and held[0] == lease.token:
                del self._producers[lease.run_id]

    def producer_state(self, run_id: UUID | str) -> Literal["untracked", "active", "expired"]:
        with self._lock:
            held = self._producers.get(str(run_id))
        if held is None:
            return "untracked"
        return "active" if held[1] > time.monotonic() else "expired"

    # -- consumer side -------------------------------------------------------------------------

    async def subscribe(self, run_id: UUID | str, *, after: str | None, heartbeat: float) -> AsyncIterator[BusItem]:
        key = str(run_id)
        try:
            cursor = int(after) if after else 0
        except ValueError:
            cursor = 0
        flag = asyncio.Event()
        loop = asyncio.get_running_loop()
        gap_reported = False
        try:
            while True:
                # Clear before reading: a publish after this point either shows up in the read below or
                # leaves the flag set, so no wake-up is ever lost.
                flag.clear()
                with self._lock:
                    log = self._runs.get(key)
                    if log is not None and (loop, flag) not in log.waiters:
                        log.waiters.append((loop, flag))
                    pending = []
                    earliest = log.entries[0][0] if log and log.entries else None
                    if log is not None:
                        pending = [(i, e) for i, e in log.entries if i > cursor]
                    latest = log.next_id - 1 if log else 0
                if earliest is not None and cursor + 1 < earliest and not gap_reported and cursor > 0:
                    gap_reported = True
                    yield StreamGap(str(cursor), str(earliest), str(latest))
                for entry_id, event in pending:
                    cursor = entry_id
                    if event is None:
                        yield END
                        return
                    yield BusEvent(event.run_id, event.kind, event.payload, event.sequence, event.occurred_at, str(entry_id))
                if pending:
                    continue
                try:
                    await asyncio.wait_for(flag.wait(), timeout=heartbeat)
                except asyncio.TimeoutError:
                    yield HEARTBEAT
        finally:
            with self._lock:
                log = self._runs.get(key)
                if log is not None and (loop, flag) in log.waiters:
                    log.waiters.remove((loop, flag))


class MemoryControl:
    """Per-Run wake-up flag; ``wait`` is called from a thread."""

    def __init__(self) -> None:
        self._flags: dict[str, threading.Event] = {}
        self._lock = threading.Lock()

    def _flag(self, run_id: UUID | str) -> threading.Event:
        with self._lock:
            return self._flags.setdefault(str(run_id), threading.Event())

    def signal(self, run_id: UUID | str, kind: str) -> None:
        self._flag(run_id).set()

    def wait(self, run_id: UUID | str, timeout: float) -> bool:
        flag = self._flag(run_id)
        if flag.wait(timeout):
            flag.clear()
            return True
        return False

    def forget(self, run_id: UUID | str) -> None:
        with self._lock:
            self._flags.pop(str(run_id), None)


class MemoryMarker:
    """Which Run of a session is live, with an expiry that activity extends."""

    def __init__(self) -> None:
        self._live: dict[str, tuple[str, float]] = {}
        self._lock = threading.Lock()

    def claim(self, session_id: UUID | str, run_id: UUID | str, ttl: float) -> None:
        with self._lock:
            self._live[str(session_id)] = (str(run_id), time.monotonic() + ttl)

    touch = claim

    def get(self, session_id: UUID | str) -> str | None:
        with self._lock:
            held = self._live.get(str(session_id))
            if held is None or held[1] <= time.monotonic():
                self._live.pop(str(session_id), None)
                return None
            return held[0]

    def clear(self, session_id: UUID | str, run_id: UUID | str) -> None:
        with self._lock:
            held = self._live.get(str(session_id))
            if held is not None and held[0] == str(run_id):
                del self._live[str(session_id)]
