"""Run watchdog acknowledgement and attention reads.

Reads and writes follow the Run read path: the principal must be a member of the tenant and must be
able to see the Run, otherwise the Run is reported as not found. Acknowledging does not change the
Run's execution; it only records that a person saw the alert and chose to keep waiting.
"""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from nexus_core.platform import Principal, RunStatus, utc_now
from nexus_platform.errors import NotFound
from nexus_platform.persistence.models.event import RunEventRecord
from nexus_platform.persistence.unit_of_work import SqlAlchemyUnitOfWork
from .ports import RunUnitOfWork, VisibleRun
from .watchdog import ACK_EVENT, ALERT_EVENT, WATCHDOG_EVENTS, needs_attention


class RunWatchdogService:
    """Record an acknowledgement inside one transaction, after authorizing the Run read."""

    def __init__(self, unit_of_work: RunUnitOfWork):
        self.unit_of_work = unit_of_work

    def acknowledge(self, principal: Principal, tenant_id: UUID, run_id: UUID) -> VisibleRun:
        """Append ``run.watchdog_ack`` to a non-terminal Run.

        Raises NotFound for invisible Runs. A terminal Run is returned unchanged, since there is
        nothing left to keep waiting for.
        """
        now = utc_now()
        with self.unit_of_work as work:
            user_id = work.access.require_principal(principal, tenant_id)
            run = work.runs.visible(tenant_id, user_id, run_id)
            if run is None:
                raise NotFound('Run not found')
            if not RunStatus(run.status).terminal:
                work.events.append(run.id, ACK_EVENT, {}, now)
            return run


def acknowledge_watchdog(session: Session, principal: Principal, tenant_id: UUID, run_id: UUID) -> VisibleRun:
    """Session-scoped facade for the HTTP layer; the caller's transaction commits the acknowledgement."""
    return RunWatchdogService(SqlAlchemyUnitOfWork(session)).acknowledge(principal, tenant_id, run_id)


def attention_required(session: Session, run_id: UUID) -> bool:
    """Whether the Run's newest watchdog alert is still unacknowledged and has no later progress.

    Computed from two sequence maxima so the event log is read once, in SQL, regardless of its length.
    """
    latest_alert = session.scalar(select(func.max(RunEventRecord.sequence)).where(
        RunEventRecord.run_id == run_id, RunEventRecord.event_type == ALERT_EVENT)) or 0
    if not latest_alert:
        return False
    latest_clear = session.scalar(select(func.max(RunEventRecord.sequence)).where(
        RunEventRecord.run_id == run_id,
        (RunEventRecord.event_type == ACK_EVENT) | RunEventRecord.event_type.not_in(WATCHDOG_EVENTS))) or 0
    return needs_attention(latest_alert, latest_clear)
