"""Principal-scoped Run reads; SQL and identity persistence stay behind transaction ports."""
from uuid import UUID
from sqlalchemy.orm import Session
from nexus_core.platform import Principal
from nexus_platform.errors import NotFound
from nexus_platform.persistence.unit_of_work import SqlAlchemyUnitOfWork
from .ports import RunUnitOfWork, VisibleRun


class RunQueryService:
    """Read one authorized Run atomically; never make an unscoped repository lookup."""
    def __init__(self, unit_of_work: RunUnitOfWork):
        self.unit_of_work = unit_of_work

    def get(self, principal: Principal, workspace_id: UUID, run_id: UUID) -> VisibleRun:
        """Resolve current membership and Run visibility, raising NotFound for invisible rows."""
        with self.unit_of_work as work:
            user_id = work.access.require_principal(principal, workspace_id)
            run = work.runs.visible(workspace_id, user_id, run_id)
            if run is None:
                raise NotFound('Run not found')
            return run


def get_run(session: Session, principal: Principal, workspace_id: UUID, run_id: UUID):
    """Compatibility facade over the transaction-scoped read service."""
    return RunQueryService(SqlAlchemyUnitOfWork(session)).get(principal, workspace_id, run_id)
