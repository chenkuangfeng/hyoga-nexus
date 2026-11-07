"""Contract for the live Run event channel (openspec 2026-11-07-run-event-streaming).

The database stays the source of truth for a Run and its durable events. The bus only carries a
live copy of them, plus ephemeral events (``message.delta``) that are never stored, so a lost or
unreachable bus changes how fast a viewer sees things, never what the Run did.

``publish`` is synchronous and thread-safe because events are produced from SQLAlchemy commit
hooks and from worker threads; ``subscribe`` is asynchronous because the API streams on its
event loop. This module depends only on the standard library.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable
from uuid import UUID

#: Event kinds that are published but never written to the database.
EPHEMERAL_KINDS = frozenset({"message.delta"})

#: Control signals a Run's worker waits for besides its periodic database check.
ControlKind = Literal["cancel"]


@dataclass(frozen=True)
class BusEvent:
    """One event on the bus.

    ``sequence`` is the durable ``run_events.sequence``; ``None`` marks an ephemeral event, which
    has no SSE ``id`` so a client's ``Last-Event-ID`` always names a durable event.
    ``cursor`` is the backend's own position (Redis Stream id, in-memory counter); it is empty for
    events read back from the database.
    """

    run_id: str
    kind: str
    payload: dict[str, Any]
    sequence: int | None = None
    occurred_at: str | None = None
    cursor: str = ""


@dataclass(frozen=True)
class StreamGap:
    """The subscriber's cursor is older than what the bus still holds.

    The caller must catch up from the database and tell the client to discard unfinished
    streamed text (``stream.resync``); it must not treat the replay as complete.
    """

    requested: str | None
    earliest: str | None
    latest: str | None


@dataclass(frozen=True)
class Heartbeat:
    """No event arrived within the heartbeat interval."""


@dataclass(frozen=True)
class End:
    """The producer will not publish more events for this Run."""


HEARTBEAT = Heartbeat()
END = End()
BusItem = BusEvent | StreamGap | Heartbeat | End


class BusUnavailable(RuntimeError):
    """The backend cannot be reached. Publishers swallow it; subscribers fall back to the database."""


@dataclass(frozen=True)
class ProducerLease:
    """Fencing token of the worker currently allowed to publish ephemeral events for a Run."""

    run_id: str
    token: str = field(default="", repr=False)


@runtime_checkable
class RunEventBus(Protocol):
    """Live event channel. Implementations: ``database``, ``memory``, ``redis``."""

    #: Backend name as configured in ``[run_events].backend``.
    name: str
    #: Whether ``message.delta`` can be kept off the database (needs somewhere else to hold it).
    supports_ephemeral: bool
    #: Whether a separate process (the API) can read what another process (a worker) published.
    cross_process: bool

    def publish(self, event: BusEvent) -> None:
        """Append an event; raises BusUnavailable when the backend is down (callers swallow it)."""

    def publish_end(self, run_id: UUID | str) -> None:
        """Tell subscribers no more events will come for this Run."""

    def tail(self, run_id: UUID | str) -> str | None:
        """Current end position, taken before a database replay so nothing falls between the two."""

    def subscribe(self, run_id: UUID | str, *, after: str | None, heartbeat: float) -> AsyncIterator[BusItem]:
        """Yield events after ``after`` (None = from the start), heartbeats, a gap, or End."""

    def cleanup(self, run_id: UUID | str) -> None:
        """Drop what the bus holds for a finished Run (after retention)."""

    def ping(self) -> bool:
        """Whether the backend answers right now."""

    def start_producer(self, run_id: UUID | str, owner: str) -> ProducerLease | None:
        """Register the worker allowed to publish ephemeral events; None when the bus does not fence."""

    def renew_producer(self, lease: ProducerLease) -> bool:
        """Extend the lease; False means it was lost and ephemeral publishing must stop."""

    def finish_producer(self, lease: ProducerLease) -> None:
        """Release the lease."""

    def producer_state(self, run_id: UUID | str) -> Literal["untracked", "active", "expired"]:
        """Liveness of the producer without inferring it from stream contents."""

    def close(self) -> None:
        """Release backend resources."""


@runtime_checkable
class ControlChannel(Protocol):
    """Wake-up for a running worker; the database remains the fact, so a lost signal only delays."""

    def signal(self, run_id: UUID | str, kind: ControlKind) -> None: ...

    def wait(self, run_id: UUID | str, timeout: float) -> bool:
        """Block up to ``timeout`` seconds; True when a signal arrived. Called from a thread."""


@runtime_checkable
class LiveRunMarker(Protocol):
    """Which Run of a session is generating now (WeKnora ``SetLiveRun`` / ``GetLiveRun``)."""

    def claim(self, session_id: UUID | str, run_id: UUID | str, ttl: float) -> None: ...

    def touch(self, session_id: UUID | str, run_id: UUID | str, ttl: float) -> None: ...

    def get(self, session_id: UUID | str) -> str | None: ...

    def clear(self, session_id: UUID | str, run_id: UUID | str) -> None: ...
