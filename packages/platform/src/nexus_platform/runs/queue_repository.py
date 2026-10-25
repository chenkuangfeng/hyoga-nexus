"""Transaction-bound Outbox lease and delivery adapter; never commits independently."""
from datetime import datetime
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.orm import Session
from nexus_core.platform import new_id
from nexus_platform.persistence.models import OutboxRecord
from .domain import Delivery


class SqlAlchemyOutboxRepository:
    """Manage deliveries using the original locks, lease ordering and completion rules."""
    def __init__(self, session: Session):
        self.session = session
        self._deliveries: dict[UUID, OutboxRecord] = {}

    def lock_delivery(self, task_id: UUID) -> Delivery | None:
        """Lock before returning worker ownership; application decides whether it may process."""
        row = self.session.scalar(select(OutboxRecord).where(
            OutboxRecord.id == task_id,
        ).with_for_update())
        if row is None:
            return None
        self._deliveries[row.id] = row
        return Delivery(row.id, row.run_id, row.message_type, row.lease_owner, row.completed_at)

    def complete_delivery(self, task_id: UUID, at: datetime, *, clear_lease: bool) -> None:
        """Complete only a previously locked delivery; preserve early-exit legacy lease fields."""
        row = self._deliveries[task_id]
        row.completed_at = at
        if clear_lease:
            row.lease_owner = None
            row.lease_until = None

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

    def enqueue(self, run_id: UUID, message_type: str, at: datetime) -> None:
        """Schedule one delivery, retaining the original per-Run/type uniqueness constraint."""
        self.session.add(OutboxRecord(
            id=new_id(), run_id=run_id, message_type=message_type,
            payload={"run_id": str(run_id)}, available_at=at, attempts=0, created_at=at,
        ))

    def complete_pending(self, run_id: UUID, at: datetime) -> None:
        """Close pending deliveries when an idle Run is cancelled; retain original lease fields."""
        for task in self.session.scalars(select(OutboxRecord).where(
            OutboxRecord.run_id == run_id, OutboxRecord.completed_at.is_(None),
        )):
            task.completed_at = at

    def has_pending(self, run_id: UUID, message_type: str) -> bool:
        """Check for the cancellation delivery under its parent Run lock."""
        return self.session.scalar(select(OutboxRecord).where(
            OutboxRecord.run_id == run_id, OutboxRecord.message_type == message_type,
            OutboxRecord.completed_at.is_(None),
        )) is not None

    def requeue_execute(self, run_id: UUID, at: datetime) -> None:
        """Reactivate the existing execution delivery under its original row lock."""
        task = self.session.scalar(select(OutboxRecord).where(
            OutboxRecord.run_id == run_id, OutboxRecord.message_type == 'run.execute',
        ).with_for_update())
        task.completed_at, task.lease_owner, task.lease_until, task.available_at = None, None, None, at
