"""ORM-free query/transaction contracts consumed by Run application services.

Repositories operate inside the caller's transaction. Visibility queries always require
tenant and authenticated user scope; unscoped lookups are not public API operations.
"""
from __future__ import annotations
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID
from nexus_core.platform import Principal


class VisibleRun(Protocol):
    """Structural legacy entity view; the persistence adapter owns its mapped identity."""
    id: UUID
    tenant_id: UUID
    principal_id: UUID
    session_id: UUID
    status: str


class StoredEvent(Protocol):
    """Ordered persisted event projection, with no dependency on SQLAlchemy."""
    id: UUID
    run_id: UUID
    sequence: int
    event_type: str
    schema_version: int
    payload: dict[str, Any]
    occurred_at: datetime


class RunRepository(Protocol):
    def visible(self, tenant_id: UUID, user_id: UUID, run_id: UUID) -> VisibleRun | None: ...


class RunEventRepository(Protocol):
    def after(self, run_id: UUID, sequence: int, limit: int) -> list[StoredEvent]: ...
    def append(self, run_id: UUID, kind: str, payload: dict[str, Any], at: datetime) -> StoredEvent: ...


class OutboxRepository(Protocol):
    def claim(self, worker_id: str, now: datetime, until: datetime) -> UUID | None: ...


class TenantAccess(Protocol):
    def require_principal(self, principal: Principal, tenant_id: UUID) -> UUID: ...


class RunUnitOfWork(Protocol):
    """Atomic application scope; repository adapters share one transaction and connection."""
    runs: RunRepository
    events: RunEventRepository
    outbox: OutboxRepository
    access: TenantAccess

    def __enter__(self) -> RunUnitOfWork: ...
    def __exit__(self, exc_type, exc_value, traceback): ...
