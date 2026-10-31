"""Legacy mapped-return facades; application services operate on independent domain objects.

Conversion returns the exact row already tracked by this operation. It must not issue a
post-commit SELECT, open another transaction or close the caller's borrowed Session.
"""
from __future__ import annotations
from typing import TYPE_CHECKING
from uuid import UUID
from nexus_core.platform import Principal

if TYPE_CHECKING:
    from sqlalchemy.orm import Session
    from nexus_platform.persistence.models import RunRecord


def create_run(session: Session, principal: Principal, tenant_id: UUID, session_id: UUID, *,
               message: str, idempotency_key: str) -> tuple[RunRecord, bool]:
    """Preserve the existing mapped return and idempotent replay flag for API callers."""
    from .submission import RunSubmissionService
    from nexus_platform.persistence.unit_of_work import SqlAlchemyUnitOfWork
    work = SqlAlchemyUnitOfWork(session)
    run, replayed = RunSubmissionService(work).submit(
        principal, tenant_id, session_id, message=message, idempotency_key=idempotency_key,
    )
    return work.runs.legacy_record(run.id), replayed


def request_cancel(session: Session, principal: Principal, tenant_id: UUID, run_id: UUID) -> RunRecord:
    """Preserve the owner-scoped cancellation signature and mapped identity."""
    from .cancellation import RunCancellationService
    from nexus_platform.persistence.unit_of_work import SqlAlchemyUnitOfWork
    work = SqlAlchemyUnitOfWork(session)
    run = RunCancellationService(work).cancel(principal, tenant_id, run_id)
    return work.runs.legacy_record(run.id)


def respond_input(db: Session, principal: Principal, tenant_id: UUID, run_id: UUID,
                  input_request_id: UUID, response: str, key: str) -> RunRecord:
    """Preserve mapped return identity without a second database lookup after commit."""
    from .inputs import RunInputService
    from nexus_platform.persistence.unit_of_work import SqlAlchemyUnitOfWork
    work = SqlAlchemyUnitOfWork(db)
    run = RunInputService(work).respond(principal, tenant_id, run_id, input_request_id, response, key)
    return work.runs.legacy_record(run.id)


def claim_next(session: Session, worker_id: str, *, lease_seconds: int) -> UUID | None:
    """Assemble lease policy without making application services depend on session creation."""
    from .leasing import RunLeaseService
    from nexus_platform.persistence.unit_of_work import SqlAlchemyUnitOfWork
    return RunLeaseService(SqlAlchemyUnitOfWork(session)).claim(worker_id, lease_seconds=lease_seconds)


def process_claimed(session: Session, task_id: UUID, worker_id: str) -> bool:
    """Assemble the retained P1 no-Runtime delivery path in the borrowed transaction scope."""
    from .leasing import RunLeaseService
    from nexus_platform.persistence.unit_of_work import SqlAlchemyUnitOfWork
    return RunLeaseService(SqlAlchemyUnitOfWork(session)).process(task_id, worker_id)
