"""Publish durable events to the bus after the transaction that wrote them commits.

Events reach ``run_events`` through several paths (submission, cancellation, lease recovery, the
worker's store). All of them go through ``SqlAlchemyRunEventRepository.append``, so that method
queues the event on the session and this hook publishes the queue once the commit is final. A
rollback drops the queue, so the bus never shows an event the database does not have.
"""
from __future__ import annotations

import logging

from sqlalchemy import event
from sqlalchemy.orm import Session

from nexus_core.run_events import BusEvent, BusUnavailable
from .factory import channels

logger = logging.getLogger("nexus_platform.run_events")
_PENDING = "run_events_pending"
#: Events after which a Run's stream is finished: it ended, or it stopped to wait for the user.
STREAM_END_KINDS = frozenset({"run.completed", "run.failed", "run.cancelled", "run.interrupted",
                              "run.waiting_input", "run.waiting_approval"})
#: A cancel request wakes the worker that is running the Run.
CANCEL_KIND = "run.cancel_requested"


def queue_event(session: Session, bus_event: BusEvent) -> None:
    """Remember a just-appended durable event until its transaction commits."""
    session.info.setdefault(_PENDING, []).append(bus_event)


def publish_event(bus_event: BusEvent) -> None:
    """Publish one event to the installed bus; a failure is logged and never raised."""
    current = channels()
    if current is None:
        return
    try:
        current.bus.publish(bus_event)
        if bus_event.kind in STREAM_END_KINDS:
            current.bus.publish_end(bus_event.run_id)
        if bus_event.kind == CANCEL_KIND:
            current.control.signal(bus_event.run_id, "cancel")
    except BusUnavailable:
        logger.warning("Run event not published to the bus", extra={"run_id": bus_event.run_id, "kind": bus_event.kind})
    except Exception:
        logger.warning("Run event publish failed", extra={"run_id": bus_event.run_id, "kind": bus_event.kind}, exc_info=True)


def _after_commit(session: Session) -> None:
    pending = session.info.pop(_PENDING, None)
    for item in pending or ():
        publish_event(item)


def _after_rollback(session: Session) -> None:
    session.info.pop(_PENDING, None)


def install_run_event_hook() -> None:
    """Register the commit and rollback listeners once for every ORM session."""
    if event.contains(Session, "after_commit", _after_commit):
        return
    event.listen(Session, "after_commit", _after_commit)
    event.listen(Session, "after_rollback", _after_rollback)
