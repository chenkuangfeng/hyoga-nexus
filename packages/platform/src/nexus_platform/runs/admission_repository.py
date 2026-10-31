"""Transaction-bound adapter from the submission flow to the dispatch ledger.

Submission uses it to append an admission and to ask whether the session is blocked by
an ``unknown`` run. It never commits; the enclosing UnitOfWork owns the transaction.
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy.orm import Session

from nexus_core.platform import new_id
from nexus_platform.errors import SessionQueueFull

from . import session_ledger


class SqlAlchemyAdmissionRepository:
    """Adapter exposing the two ledger operations the submission flow needs."""

    def __init__(self, session: Session):
        self.session = session

    def enqueue(self, session_id: UUID, run_id: UUID, at: datetime) -> int:
        """Append the Run to its session FIFO and return its 1-based position.

        Raises ``SessionQueueFull`` (HTTP 409) when the session already has the maximum queued.
        """
        try:
            session_ledger.enqueue(
                self.session, session_id=session_id, run_id=run_id, admission_id=new_id(), now=at,
            )
        except session_ledger.QueueFull as exc:
            raise SessionQueueFull(str(exc)) from exc
        position = session_ledger.queue_position(self.session, run_id)
        assert position is not None
        return position

    def blocked(self, session_id: UUID) -> bool:
        """True when the session has a ``started`` or ``unknown`` admission."""
        return session_ledger.session_blocked(self.session, session_id)
