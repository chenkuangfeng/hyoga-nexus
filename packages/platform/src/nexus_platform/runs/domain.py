"""Run write models, independent of ORM identity and transaction infrastructure."""
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID


@dataclass
class Run:
    """One Run's persisted state copied into the application transaction.

    Changing this object has no implicit database effect. The repository must explicitly
    save it under the original Run lock; legacy API callers receive mapped rows separately.
    """
    id: UUID
    tenant_id: UUID
    session_id: UUID
    principal_id: UUID
    status: str
    idempotency_key: str
    request_hash: str
    config_snapshot: dict[str, Any]
    created_at: datetime
    attempt: int = 0
    lease_owner: str | None = None
    lease_until: datetime | None = None
    cancel_requested_at: datetime | None = None
    error_code: str | None = None
    error_message: str | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None


@dataclass(frozen=True)
class PendingInput:
    """Input-consumption state; the containing Run lock serializes responses and cancellation."""
    id: UUID
    run_id: UUID
    response: str | None
    response_key: str | None
    responded_at: datetime | None


@dataclass(frozen=True)
class Delivery:
    """Locked worker delivery identity and ownership, distinct from a user's Run authority."""
    id: UUID
    run_id: UUID
    message_type: str
    lease_owner: str | None
    completed_at: datetime | None
