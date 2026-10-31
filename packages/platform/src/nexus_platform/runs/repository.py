"""SQLAlchemy Run identity, owner locking, explicit writes and idempotency savepoints.

Nexus scope is always explicit. Separate adapters own event allocation and queue delivery;
compatibility re-exports retain the earlier internal repository import paths.
"""
from copy import deepcopy
from dataclasses import fields
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from nexus_platform.persistence.models import RunRecord, SessionRecord
from .domain import Delivery, Run
from .event_repository import SqlAlchemyRunEventRepository
from .queue_repository import SqlAlchemyOutboxRepository


class SqlAlchemyRunRepository:
    """Keep mapped identity inside the adapter and return independent write-side Run values."""
    def __init__(self, session: Session):
        self.session = session
        self._records: dict[UUID, RunRecord] = {}

    def visible(self, tenant_id: UUID, user_id: UUID, run_id: UUID) -> RunRecord | None:
        """Legacy read projection for Run principal or Session owner, scoped to one tenant."""
        return self.session.scalar(
            select(RunRecord).join(SessionRecord, SessionRecord.id == RunRecord.session_id).where(
                RunRecord.id == run_id, RunRecord.tenant_id == tenant_id,
                (RunRecord.principal_id == user_id) | (SessionRecord.owner_user_id == user_id),
            )
        )

    def _remember(self, row: RunRecord) -> Run:
        self._records[row.id] = row
        return Run(**{field.name: deepcopy(getattr(row, field.name)) for field in fields(Run)})

    def owned_for_update(self, tenant_id: UUID, user_id: UUID, run_id: UUID) -> Run | None:
        """Lock a Run strictly owned by this principal; never reuse broader read visibility."""
        row = self.session.scalar(select(RunRecord).where(
            RunRecord.id == run_id, RunRecord.tenant_id == tenant_id,
            RunRecord.principal_id == user_id,
        ).with_for_update())
        return self._remember(row) if row is not None else None

    def for_delivery(self, delivery: Delivery) -> Run | None:
        """Worker-only load after the service validates the locked delivery's lease owner.

        User-facing operations must use owned_for_update; this is not a visibility fallback.
        """
        row = self.session.scalar(select(RunRecord).where(
            RunRecord.id == delivery.run_id,
        ).with_for_update())
        return self._remember(row) if row is not None else None

    def by_key(self, tenant_id: UUID, user_id: UUID, key: str) -> Run | None:
        """Look up the existing request only within its authenticated idempotency scope."""
        row = self.session.scalar(select(RunRecord).where(
            RunRecord.tenant_id == tenant_id, RunRecord.principal_id == user_id,
            RunRecord.idempotency_key == key,
        ))
        return self._remember(row) if row is not None else None

    def has_active(self, session_id: UUID) -> bool:
        """Check the submission Session already locked and authorized by the application."""
        return self.session.scalar(select(RunRecord.id).where(
            RunRecord.session_id == session_id,
            RunRecord.status.in_(['queued', 'running', 'waiting_input', 'waiting_approval']),
        ).limit(1)) is not None

    def insert_or_replay(self, run: Run) -> tuple[Run, bool]:
        """Insert under a savepoint; resolve only a scoped key collision, not other DB failures."""
        row = RunRecord(**{field.name: deepcopy(getattr(run, field.name)) for field in fields(Run)})
        try:
            with self.session.begin_nested():
                self.session.add(row)
                self.session.flush()
        except IntegrityError:
            existing = self.by_key(run.tenant_id, run.principal_id, run.idempotency_key)
            if existing is None:
                raise
            return existing, False
        return self._remember(row), True

    def save(self, run: Run) -> None:
        """Apply explicit state to a previously inserted/locked Run; do not issue an unscoped read."""
        row = self._records[run.id]
        for field in fields(Run):
            setattr(row, field.name, deepcopy(getattr(run, field.name)))

    def legacy_record(self, run_id: UUID) -> RunRecord:
        """Return the already tracked mapped identity after commit, with no new query/transaction.

        This is for the compatibility facade only and is intentionally absent from the
        application repository protocol. Unknown IDs fail rather than performing a lookup.
        """
        return self._records[run_id]
