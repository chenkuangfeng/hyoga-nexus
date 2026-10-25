"""SQLAlchemy adapters for scoped Run access, ordered events and queue claims.

Responsibility mapping follows WeKnora application/repository and interfaces/session
(e1f9a6166); this adapter preserves Nexus Workspace/Principal keys and transaction locks.
It does not copy GORM code or weaken scope through a tenant-only query.
"""
from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from nexus_core.platform import new_id
from nexus_platform.persistence.models import OutboxRecord, RunEventRecord, RunRecord, SessionRecord


class SqlAlchemyRunRepository:
    """Workspace and principal-filtered Run queries in an existing transaction."""
    def __init__(self, session: Session):
        self.session = session

    def visible(self, workspace_id: UUID, user_id: UUID, run_id: UUID) -> RunRecord | None:
        """Return a Run only to its principal or its Session owner in the same workspace."""
        return self.session.scalar(select(RunRecord).join(SessionRecord, SessionRecord.id == RunRecord.session_id).where(
            RunRecord.id == run_id, RunRecord.workspace_id == workspace_id,
            (RunRecord.principal_id == user_id) | (SessionRecord.owner_user_id == user_id)))


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
        return row


class SqlAlchemyOutboxRepository:
    """Claim one available queue entry using the existing lease and ordering rules."""
    def __init__(self, session: Session):
        self.session = session

    def claim(self, worker_id: str, now: datetime, until: datetime) -> UUID | None:
        """Lock the oldest available/expired entry, skip locked rows and update its lease."""
        task = self.session.scalar(select(OutboxRecord).where(
            OutboxRecord.completed_at.is_(None), OutboxRecord.available_at <= now,
            (OutboxRecord.lease_until.is_(None)) | (OutboxRecord.lease_until <= now))
            .order_by(OutboxRecord.available_at, OutboxRecord.created_at, OutboxRecord.id)
            .limit(1).with_for_update(skip_locked=True))
        if task is None:
            return None
        task.lease_owner, task.lease_until = worker_id, until
        task.attempts += 1
        return task.id
