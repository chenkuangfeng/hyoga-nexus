from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from nexus_core.platform import Principal, WorkspaceRole, new_id, utc_now
from nexus_platform.errors import Conflict, Forbidden, NotFound
from nexus_platform.identity.service import require_membership, require_workspace, resolve_user
from nexus_platform.persistence.models import (
    AuditRecord,
    MembershipRecord,
    PlatformResourceRecord,
    ResourceGrantRecord,
    WorkspaceRecord,
)


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


def register_resource(
    session: Session,
    *,
    workspace_id: UUID,
    kind: str,
    resource_id: str,
    version_id: str | None,
) -> PlatformResourceRecord:
    """Registration port called by a resource package after it owns/creates a version."""
    require_workspace(session, workspace_id)
    normalized_version = version_id or ""
    row = session.scalar(
        select(PlatformResourceRecord).where(
            PlatformResourceRecord.workspace_id == workspace_id,
            PlatformResourceRecord.kind == kind,
            PlatformResourceRecord.resource_id == resource_id,
            PlatformResourceRecord.version_id == normalized_version,
        )
    )
    if row is not None:
        row.active = True
        return row
    row = PlatformResourceRecord(
        id=new_id(),
        workspace_id=workspace_id,
        kind=kind,
        resource_id=resource_id,
        version_id=normalized_version,
        active=True,
        created_at=utc_now(),
    )
    session.add(row)
    session.flush()
    return row


def deactivate_resource(
    session: Session, *, workspace_id: UUID, kind: str, resource_id: str, version_id: str | None
) -> None:
    row = session.scalar(
        select(PlatformResourceRecord).where(
            PlatformResourceRecord.workspace_id == workspace_id,
            PlatformResourceRecord.kind == kind,
            PlatformResourceRecord.resource_id == resource_id,
            PlatformResourceRecord.version_id == (version_id or ""),
        ).with_for_update()
    )
    if row is None:
        raise NotFound("Resource not found")
    row.active = False


def grant_resource(
    session: Session,
    principal: Principal,
    *,
    source_workspace_id: UUID,
    target_workspace_id: UUID,
    kind: str,
    resource_id: str,
    permissions: list[str],
) -> ResourceGrantRecord:
    if source_workspace_id == target_workspace_id:
        raise ValueError("A resource grant must target a different workspace")
    now = utc_now()
    with session.begin():
        actor = resolve_user(session, principal)
        require_workspace(session, source_workspace_id)
        require_workspace(session, target_workspace_id)
        require_membership(session, source_workspace_id, actor.id, roles=ADMIN_ROLES)
        source_resource = session.scalar(
            select(PlatformResourceRecord).where(
                PlatformResourceRecord.workspace_id == source_workspace_id,
                PlatformResourceRecord.kind == kind,
                PlatformResourceRecord.resource_id == resource_id,
                PlatformResourceRecord.active.is_(True),
            )
        )
        if source_resource is None:
            raise NotFound("Resource not found")
        if not permissions or any(p not in {"read", "use"} for p in permissions):
            raise ValueError("Resource grant permissions must contain read or use")
        grant = session.scalar(
            select(ResourceGrantRecord).where(
                ResourceGrantRecord.source_workspace_id == source_workspace_id,
                ResourceGrantRecord.target_workspace_id == target_workspace_id,
                ResourceGrantRecord.kind == kind,
                ResourceGrantRecord.resource_id == resource_id,
            )
        )
        if grant is None:
            grant = ResourceGrantRecord(
                id=new_id(),
                source_workspace_id=source_workspace_id,
                target_workspace_id=target_workspace_id,
                kind=kind,
                resource_id=resource_id,
                permissions=sorted(set(permissions)),
                created_by=actor.id,
                created_at=now,
            )
            session.add(grant)
        else:
            grant.permissions = sorted(set(permissions))
            grant.created_by = actor.id
            grant.created_at = now
            grant.revoked_at = None
        audit(
            session,
            source_workspace_id,
            actor.id,
            "resource.granted",
            kind,
            resource_id,
            {"target_workspace_id": str(target_workspace_id), "permissions": sorted(set(permissions))},
        )
    return grant


def revoke_resource_grant(session: Session, principal: Principal, grant_id: UUID) -> None:
    now = utc_now()
    with session.begin():
        actor = resolve_user(session, principal)
        grant = session.get(ResourceGrantRecord, grant_id)
        if grant is None or grant.revoked_at is not None:
            raise NotFound("Resource grant not found")
        require_membership(session, grant.source_workspace_id, actor.id, roles=ADMIN_ROLES)
        grant.revoked_at = now
        audit(session, grant.source_workspace_id, actor.id, "resource.grant_revoked", grant.kind, grant.resource_id)


def authorize_resource(
    session: Session,
    workspace_id: UUID,
    kind: str,
    resource_id: str,
    *,
    source_workspace_id: UUID | None = None,
    resource_version_id: str | None = None,
    permission: str = "use",
) -> PlatformResourceRecord:
    """Recheck resource status and current grant at the actual operation boundary."""
    if source_workspace_id is None or source_workspace_id == workspace_id:
        direct = session.scalar(
            select(PlatformResourceRecord).where(
                PlatformResourceRecord.workspace_id == workspace_id,
                PlatformResourceRecord.kind == kind,
                PlatformResourceRecord.resource_id == resource_id,
                PlatformResourceRecord.version_id == (resource_version_id or ""),
                PlatformResourceRecord.active.is_(True),
            )
        )
        if direct is not None:
            return direct
    shared = session.execute(
        select(PlatformResourceRecord, ResourceGrantRecord)
        .join(ResourceGrantRecord, ResourceGrantRecord.source_workspace_id == PlatformResourceRecord.workspace_id)
        .where(
            ResourceGrantRecord.target_workspace_id == workspace_id,
            *([ResourceGrantRecord.source_workspace_id == source_workspace_id] if source_workspace_id else []),
            ResourceGrantRecord.kind == kind,
            ResourceGrantRecord.resource_id == resource_id,
            ResourceGrantRecord.revoked_at.is_(None),
            PlatformResourceRecord.kind == kind,
            PlatformResourceRecord.resource_id == resource_id,
            PlatformResourceRecord.version_id == (resource_version_id or ""),
            PlatformResourceRecord.active.is_(True),
        )
    ).all()
    shared = next((row for row in shared if permission in row[1].permissions), None)
    if shared is None:
        raise Forbidden("Resource is unavailable or its grant was revoked")
    return shared[0]


def audit(
    session: Session,
    workspace_id: UUID,
    actor_user_id: UUID,
    action: str,
    target_type: str,
    target_id: str,
    metadata: dict[str, object] | None = None,
) -> None:
    session.add(
        AuditRecord(
            id=new_id(),
            workspace_id=workspace_id,
            actor_user_id=actor_user_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            result="success",
            metadata_json=metadata or {},
            created_at=utc_now(),
        )
    )


def lock_workspace(session: Session, workspace_id: UUID) -> WorkspaceRecord:
    workspace = session.scalar(
        select(WorkspaceRecord).where(WorkspaceRecord.id == workspace_id).with_for_update()
    )
    if workspace is None or workspace.status != "active":
        raise NotFound("Workspace not found")
    return workspace
