"""Transaction-bound event allocation/replay adapter; never commits independently."""
from datetime import datetime
from uuid import UUID
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from nexus_core.platform import new_id
from nexus_platform.persistence.models import RunEventRecord


class SqlAlchemyRunEventRepository:
    """Event allocation under the caller's parent-Run lock; replay never performs execution."""
    def __init__(self, session: Session):
        self.session = session

    def after(self, run_id: UUID, sequence: int, limit: int) -> list[RunEventRecord]:
        """Read events in sequence order, excluding the supplied cursor."""
        return list(self.session.scalars(select(RunEventRecord).where(
            RunEventRecord.run_id == run_id, RunEventRecord.sequence > sequence)
            .order_by(RunEventRecord.sequence).limit(limit)))

    def append(self, run_id: UUID, kind: str, payload: dict, at: datetime) -> RunEventRecord:
        """Allocate the next sequence and flush; caller must hold the parent Run lock.

        Flush preserves the existing uniqueness/foreign-key error behavior. This method
        never commits so event, audit and related state updates stay atomic.
        """
        sequence = self.session.scalar(select(func.coalesce(func.max(RunEventRecord.sequence), 0)).where(
            RunEventRecord.run_id == run_id)) + 1
        row = RunEventRecord(id=new_id(), run_id=run_id, sequence=sequence, event_type=kind,
                             schema_version=1, payload=payload, occurred_at=at)
        self.session.add(row)
        self.session.flush()
        # Published to the live bus only once this transaction commits (runs/bus/hook.py).
        from nexus_platform.runs.bus.hook import queue_event
        from nexus_core.run_events import BusEvent
        queue_event(self.session, BusEvent(str(run_id), kind, payload, sequence, at.isoformat() if at else None))
        return row
