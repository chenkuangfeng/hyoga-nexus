"""Session-bound authorization adapter used by transaction-scoped application services."""
from uuid import UUID
from sqlalchemy.orm import Session
from nexus_core.platform import Principal
from .service import resolve_user, require_workspace, require_membership


class SqlAlchemyWorkspaceAccess:
    """Resolve an active user and membership within the same database transaction as access."""
    def __init__(self, session: Session):
        self.session = session

    def require_principal(self, principal: Principal, workspace_id: UUID) -> UUID:
        """Return the active principal's user ID or preserve the existing scope rejection."""
        user = resolve_user(self.session, principal)
        require_workspace(self.session, workspace_id)
        require_membership(self.session, workspace_id, user.id)
        return user.id
