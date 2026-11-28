"""Authorized reads for durable model request trajectory records."""
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.orm import Session
from nexus_core.platform import Principal
from nexus_platform.persistence.models import RunTrajectoryRecord
from .queries import get_run


def list_trajectory_records(session: Session, principal: Principal, tenant_id: UUID, run_id: UUID):
    """Return request snapshots only after applying the canonical Run visibility check."""
    get_run(session, principal, tenant_id, run_id)
    return list(session.scalars(select(RunTrajectoryRecord)
        .where(RunTrajectoryRecord.run_id == run_id)
        .order_by(RunTrajectoryRecord.sequence)))
