from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus_core.platform import Principal, new_id, utc_now
from nexus_platform.errors import Forbidden, NotFound
from nexus_platform.persistence.models import MembershipRecord, UserRecord, WorkspaceRecord


def resolve_user(session: Session, principal: Principal) -> UserRecord:
    user = session.scalar(
        select(UserRecord).where(UserRecord.issuer == principal.issuer, UserRecord.subject == principal.id)
    )
    if user is not None:
        if user.status != "active":
            raise Forbidden("The authenticated user is disabled")
        return user
    user = UserRecord(
        id=new_id(), issuer=principal.issuer, subject=principal.id, status="active", created_at=utc_now()
    )
    session.add(user)
    session.flush()
    return user


def require_membership(
    session: Session, workspace_id: UUID, user_id: UUID, *, roles: set[str] | None = None
) -> MembershipRecord:
    membership = session.get(MembershipRecord, (workspace_id, user_id))
    if membership is None or membership.status != "active":
        raise NotFound("Workspace not found")
    if roles is not None and membership.role not in roles:
        raise Forbidden("Your workspace role does not allow this action")
    return membership


def require_workspace(session: Session, workspace_id: UUID) -> WorkspaceRecord:
    workspace = session.get(WorkspaceRecord, workspace_id)
    if workspace is None or workspace.status != "active":
        raise NotFound("Workspace not found")
    return workspace
