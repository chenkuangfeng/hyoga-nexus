"""Authorized event replay and caller-transaction event writing; never execute a Run."""
from datetime import datetime
from typing import Any
from uuid import UUID
from sqlalchemy.orm import Session
from nexus_core.platform import Principal, utc_now
from nexus_platform.errors import NotFound
from nexus_platform.persistence.unit_of_work import SqlAlchemyUnitOfWork
from .ports import RunUnitOfWork, RunEventRepository, StoredEvent
from .repository import SqlAlchemyRunEventRepository


class RunEventService:
    """Resolve the principal and replay ordered events in the same transaction."""
    def __init__(self, unit_of_work: RunUnitOfWork):
        self.unit_of_work = unit_of_work

    def list(self, principal: Principal, tenant_id: UUID, run_id: UUID,
             after_sequence: int, limit: int = 200) -> list[StoredEvent]:
        """Return the exclusive cursor page; invisible Runs raise NotFound before reading events."""
        with self.unit_of_work as work:
            user_id = work.access.require_principal(principal, tenant_id)
            run = work.runs.visible(tenant_id, user_id, run_id)
            if run is None:
                raise NotFound('Run not found')
            return work.events.after(run.id, after_sequence, limit)


class RunEventWriter:
    """Append using an existing transaction and parent Run lock; no independent commit."""
    def __init__(self, repository: RunEventRepository):
        self.repository = repository

    def append(self, run_id: UUID, kind: str, payload: dict[str, Any], at: datetime) -> StoredEvent:
        """Allocate and flush the event; caller rollback also removes this event."""
        return self.repository.append(run_id, kind, payload, at)


def list_events(session: Session, principal: Principal, tenant_id: UUID, run_id: UUID,
                after_sequence: int, limit: int = 200):
    """Keep the existing API/SSE call signature while using scoped repositories."""
    return RunEventService(SqlAlchemyUnitOfWork(session)).list(principal, tenant_id, run_id, after_sequence, limit)


def append_event(session: Session, run_id: UUID, event_type: str, payload: dict[str, Any], occurred_at=None):
    """Compatibility append; the caller still owns transaction and parent Run lock."""
    return RunEventWriter(SqlAlchemyRunEventRepository(session)).append(run_id, event_type, payload, occurred_at or utc_now())
