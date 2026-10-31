from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from nexus_core.platform import Principal, WorkspaceRole, new_id, utc_now
from nexus_platform.errors import Conflict, Forbidden, NotFound
from nexus_platform.authz.audit import audit
from nexus_platform.identity.service import require_membership, require_workspace, resolve_user
from nexus_platform.persistence.models import MembershipRecord, WorkspaceRecord


ADMIN_ROLES = {WorkspaceRole.OWNER.value, WorkspaceRole.ADMIN.value}


def create_workspace(session: Session, principal: Principal, name: str) -> WorkspaceRecord:
    name = name.strip()
    if not name:
        raise ValueError("Workspace name must not be empty")
    now = utc_now()
    with session.begin():
        user = resolve_user(session, principal)
        workspace = WorkspaceRecord(
            id=new_id(), name=name, status="active", created_by=user.id, created_at=now, updated_at=now
        )
        session.add(workspace)
        session.flush()
        session.add(
            MembershipRecord(
                workspace_id=workspace.id,
                user_id=user.id,
                role=WorkspaceRole.OWNER.value,
                status="active",
                joined_at=now,
            )
        )
        audit(session, workspace.id, user.id, "workspace.created", "workspace", str(workspace.id))
    return workspace


def list_workspaces(session: Session, principal: Principal) -> list[tuple[WorkspaceRecord, str]]:
    with session.begin():
        user = resolve_user(session, principal)
        rows = session.execute(
            select(WorkspaceRecord, MembershipRecord.role)
            .join(MembershipRecord, MembershipRecord.workspace_id == WorkspaceRecord.id)
            .where(
                MembershipRecord.user_id == user.id,
                MembershipRecord.status == "active",
                WorkspaceRecord.status == "active",
            )
            .order_by(WorkspaceRecord.created_at)
        ).all()
    return [(row[0], row[1]) for row in rows]


def add_member(
    session: Session,
    principal: Principal,
    workspace_id: UUID,
    new_principal: Principal,
    role: WorkspaceRole,
) -> MembershipRecord:
    if role == WorkspaceRole.OWNER:
        raise Forbidden("Owner transfer must use the ownership transfer action")
    now = utc_now()
    with session.begin():
        actor = resolve_user(session, principal)
        require_workspace(session, workspace_id)
        require_membership(session, workspace_id, actor.id, roles=ADMIN_ROLES)
        user = resolve_user(session, new_principal)
        membership = session.get(MembershipRecord, (workspace_id, user.id))
        if membership and membership.status == "active":
            raise Conflict("User is already an active member")
        if membership:
            membership.role = role.value
            membership.status = "active"
            membership.joined_at = now
            membership.revoked_at = None
        else:
            membership = MembershipRecord(
                workspace_id=workspace_id,
                user_id=user.id,
                role=role.value,
                status="active",
                joined_at=now,
            )
            session.add(membership)
        audit(session, workspace_id, actor.id, "workspace.member_added", "user", str(user.id), {"role": role.value})
    return membership


def update_member_role(
    session: Session, principal: Principal, workspace_id: UUID, member_id: UUID, role: WorkspaceRole
) -> MembershipRecord:
    now = utc_now()
    with session.begin():
        actor = resolve_user(session, principal)
        lock_workspace(session, workspace_id)
        actor_membership = require_membership(session, workspace_id, actor.id, roles=ADMIN_ROLES)
        member = session.get(MembershipRecord, (workspace_id, member_id))
        if member is None or member.status != "active":
            raise NotFound("Workspace member not found")
        if actor_membership.role != WorkspaceRole.OWNER.value and (
            role == WorkspaceRole.OWNER or member.role == WorkspaceRole.OWNER.value
        ):
            raise Forbidden("Only an owner can transfer or modify owner membership")
        if member.role == WorkspaceRole.OWNER.value and role != WorkspaceRole.OWNER:
            owner_count = session.scalar(
                select(func.count()).select_from(MembershipRecord).where(
                    MembershipRecord.workspace_id == workspace_id,
                    MembershipRecord.status == "active",
                    MembershipRecord.role == WorkspaceRole.OWNER.value,
                )
            )
            if owner_count <= 1:
                raise Conflict("A workspace must keep at least one owner")
        member.role = role.value
        audit(session, workspace_id, actor.id, "workspace.member_role_changed", "user", str(member_id), {"role": role.value})
    return member


def remove_member(session: Session, principal: Principal, workspace_id: UUID, member_id: UUID) -> None:
    now = utc_now()
    with session.begin():
        actor = resolve_user(session, principal)
        lock_workspace(session, workspace_id)
        actor_membership = require_membership(session, workspace_id, actor.id, roles=ADMIN_ROLES)
        member = session.get(MembershipRecord, (workspace_id, member_id))
        if member is None or member.status != "active":
            raise NotFound("Workspace member not found")
        if member.role == WorkspaceRole.OWNER.value:
            if actor_membership.role != WorkspaceRole.OWNER.value:
                raise Forbidden("Only an owner can remove an owner")
            owner_count = session.scalar(
                select(func.count()).select_from(MembershipRecord).where(
                    MembershipRecord.workspace_id == workspace_id,
                    MembershipRecord.status == "active",
                    MembershipRecord.role == WorkspaceRole.OWNER.value,
                )
            )
            if owner_count <= 1:
                raise Conflict("Transfer ownership before removing the last owner")
        member.status = "revoked"
        member.revoked_at = now
        audit(session, workspace_id, actor.id, "workspace.member_removed", "user", str(member_id))


def lock_workspace(session: Session, workspace_id: UUID) -> WorkspaceRecord:
    workspace = session.scalar(
        select(WorkspaceRecord).where(WorkspaceRecord.id == workspace_id).with_for_update()
    )
    if workspace is None or workspace.status != "active":
        raise NotFound("Workspace not found")
    return workspace
