from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from nexus_core.platform import Principal, TenantRole, new_id, utc_now
from nexus_platform.tenants.builtin_roles import ensure_builtin_roles
from nexus_platform.errors import Conflict, Forbidden, NotFound
from nexus_platform.authz.audit import audit
from nexus_platform.orgs.access import is_space_manager, membership_is_active
from nexus_platform.identity.service import require_membership, require_tenant, resolve_user
from nexus_platform.authz.permissions import require_api_permission
from nexus_platform.persistence.models import MembershipRecord, TenantRecord


ADMIN_ROLES = {TenantRole.OWNER.value, TenantRole.ADMIN.value}


def create_tenant(session: Session, principal: Principal, name: str) -> TenantRecord:
    name = name.strip()
    if not name:
        raise ValueError("Tenant name must not be empty")
    now = utc_now()
    with session.begin():
        user = resolve_user(session, principal)
        tenant = TenantRecord(
            id=new_id(), name=name, status="active", created_by=user.id, created_at=now, updated_at=now
        )
        session.add(tenant)
        session.flush()
        ensure_builtin_roles(session, tenant.id)
        session.add(
            MembershipRecord(
                tenant_id=tenant.id,
                user_id=user.id,
                role=TenantRole.OWNER.value,
                status="active",
                joined_at=now,
            )
        )
        audit(session, tenant.id, user.id, "tenant.created", "tenant", str(tenant.id))
    return tenant


def list_tenants(session: Session, principal: Principal) -> list[tuple[TenantRecord, str]]:
    """Active spaces the user can enter, as (space, role). Personal and enterprise spaces are listed alike."""
    with session.begin():
        user = resolve_user(session, principal)
        rows = session.execute(
            select(TenantRecord, MembershipRecord)
            .join(MembershipRecord, MembershipRecord.tenant_id == TenantRecord.id)
            .where(
                MembershipRecord.user_id == user.id,
                MembershipRecord.status == "active",
                TenantRecord.status == "active",
            )
            .order_by(TenantRecord.created_at)
        ).all()
        return [(tenant, membership.role) for tenant, membership in rows if membership_is_active(session, membership)]


def current_space(session: Session, principal: Principal, tenant_id: UUID) -> tuple[TenantRecord, str]:
    """The space and the caller's role in it. Non-members get NotFound, so a space id is not disclosed."""
    with session.begin():
        actor = resolve_user(session, principal)
        tenant = require_tenant(session, tenant_id)
        membership = require_membership(session, tenant_id, actor.id)
        return tenant, membership.role


def update_space(
    session: Session, principal: Principal, tenant_id: UUID, *, name: str | None = None,
    description: str | None = None,
) -> TenantRecord:
    """Change the space name and/or description. Owners and admins only.

    `None` leaves a field unchanged. The name is 1-160 characters after trimming; the description is at most
    500 characters and an empty string clears it.
    """
    if name is None and description is None:
        raise ValueError("Nothing to update")
    if name is not None:
        name = name.strip()
        if not name or len(name) > 160:
            raise ValueError("Space name must be 1-160 characters")
    if description is not None:
        description = description.strip()
        if len(description) > 500:
            raise ValueError("Space description must be at most 500 characters")
    now = utc_now()
    with session.begin():
        actor = resolve_user(session, principal)
        tenant = lock_tenant(session, tenant_id)
        require_membership(session, tenant_id, actor.id)
        if not is_space_manager(session, tenant_id, actor.id):
            raise Forbidden("Only a space owner or admin can change the space")
        changes: dict[str, dict[str, str | None]] = {}
        if name is not None and name != tenant.name:
            changes["name"] = {"from": tenant.name, "to": name}
            tenant.name = name
        if description is not None:
            new_description = description or None
            if new_description != tenant.description:
                changes["description"] = {"from": tenant.description, "to": new_description}
                tenant.description = new_description
        if changes:
            tenant.updated_at = now
            audit(session, tenant_id, actor.id, "tenant.updated", "tenant", str(tenant_id), changes)
    return tenant


def delete_space(session: Session, principal: Principal, tenant_id: UUID) -> None:
    """Archive an enterprise space so it disappears from every member's space list.

    Owner only. Personal spaces cannot be deleted, and a space that still created active shared spaces must
    have them deleted first (a shared space keeps its creating space as its owner).
    Archiving keeps the rows, so audit history remains; the space stops accepting requests (404).
    """
    from nexus_platform.persistence.models import SharedSpaceRecord

    now = utc_now()
    with session.begin():
        actor = resolve_user(session, principal)
        tenant = lock_tenant(session, tenant_id)
        membership = require_membership(session, tenant_id, actor.id)
        if membership.role != TenantRole.OWNER.value:
            raise Forbidden("Only the space owner can delete the space")
        owned_shared = session.scalar(select(func.count()).select_from(SharedSpaceRecord).where(
            SharedSpaceRecord.owner_tenant_id == tenant_id, SharedSpaceRecord.deleted_at.is_(None))) or 0
        if owned_shared:
            raise Conflict("Delete the shared spaces this space created before deleting the space")
        tenant.status = "archived"
        tenant.updated_at = now
        audit(session, tenant_id, actor.id, "tenant.archived", "tenant", str(tenant_id))


def add_member(
    session: Session,
    principal: Principal,
    tenant_id: UUID,
    new_principal: Principal,
    role: TenantRole,
) -> MembershipRecord:
    if role == TenantRole.OWNER:
        raise Forbidden("Owner transfer must use the ownership transfer action")
    now = utc_now()
    with session.begin():
        actor = resolve_user(session, principal)
        require_tenant(session, tenant_id)
        require_membership(session, tenant_id, actor.id)
        require_api_permission(session, tenant_id, actor.id, "members:manage")
        user = resolve_user(session, new_principal)
        membership = session.get(MembershipRecord, (tenant_id, user.id))
        if membership and membership.status == "active":
            raise Conflict("User is already an active member")
        if membership and membership.status == "suspended":
            raise Conflict("Membership is suspended; restore it before rejoining")
        if membership:
            membership.role = role.value
            membership.status = "active"
            membership.joined_at = now
            membership.revoked_at = None
            membership.suspended_at = None
        else:
            membership = MembershipRecord(
                tenant_id=tenant_id,
                user_id=user.id,
                role=role.value,
                status="active",
                joined_at=now,
            )
            session.add(membership)
        audit(session, tenant_id, actor.id, "tenant.member_added", "user", str(user.id), {"role": role.value})
    return membership


def update_member_role(
    session: Session, principal: Principal, tenant_id: UUID, member_id: UUID, role: TenantRole
) -> MembershipRecord:
    now = utc_now()
    with session.begin():
        actor = resolve_user(session, principal)
        lock_tenant(session, tenant_id)
        actor_membership = require_membership(session, tenant_id, actor.id)
        require_api_permission(session, tenant_id, actor.id, "members:manage")
        member = session.get(MembershipRecord, (tenant_id, member_id))
        if member is None or member.status != "active":
            raise NotFound("Tenant member not found")
        if actor_membership.role != TenantRole.OWNER.value and (
            role == TenantRole.OWNER or member.role == TenantRole.OWNER.value
        ):
            raise Forbidden("Only an owner can transfer or modify owner membership")
        if member.role == TenantRole.OWNER.value and role != TenantRole.OWNER:
            owner_count = session.scalar(
                select(func.count()).select_from(MembershipRecord).where(
                    MembershipRecord.tenant_id == tenant_id,
                    MembershipRecord.status == "active",
                    MembershipRecord.role == TenantRole.OWNER.value,
                )
            )
            if owner_count <= 1:
                raise Conflict("A tenant must keep at least one owner")
        member.role = role.value
        audit(session, tenant_id, actor.id, "tenant.member_role_changed", "user", str(member_id), {"role": role.value})
    return member


def remove_member(session: Session, principal: Principal, tenant_id: UUID, member_id: UUID) -> None:
    now = utc_now()
    with session.begin():
        actor = resolve_user(session, principal)
        lock_tenant(session, tenant_id)
        actor_membership = require_membership(session, tenant_id, actor.id)
        require_api_permission(session, tenant_id, actor.id, "members:manage")
        member = session.get(MembershipRecord, (tenant_id, member_id))
        if member is None or member.status not in {"active", "suspended"}:
            raise NotFound("Tenant member not found")
        if member.role == TenantRole.OWNER.value:
            if actor_membership.role != TenantRole.OWNER.value:
                raise Forbidden("Only an owner can remove an owner")
            owner_count = session.scalar(
                select(func.count()).select_from(MembershipRecord).where(
                    MembershipRecord.tenant_id == tenant_id,
                    MembershipRecord.status == "active",
                    MembershipRecord.role == TenantRole.OWNER.value,
                )
            )
            if owner_count <= 1:
                raise Conflict("Transfer ownership before removing the last owner")
        member.status = "revoked"
        member.revoked_at = now
        member.suspended_at = None
        audit(session, tenant_id, actor.id, "tenant.member_removed", "user", str(member_id))


def set_member_status(
    session: Session, principal: Principal, tenant_id: UUID, member_id: UUID, status: str
) -> MembershipRecord:
    """Suspend or restore a member while preserving their role, organization links and history."""
    if status not in {"active", "suspended"}:
        raise ValueError("Member status must be active or suspended")
    now = utc_now()
    with session.begin():
        actor = resolve_user(session, principal)
        lock_tenant(session, tenant_id)
        actor_membership = require_membership(session, tenant_id, actor.id)
        require_api_permission(session, tenant_id, actor.id, "members:manage")
        member = session.get(MembershipRecord, (tenant_id, member_id))
        if member is None or member.status not in {"active", "suspended"}:
            raise NotFound("Tenant member not found")
        if member.role == TenantRole.OWNER.value and actor_membership.role != TenantRole.OWNER.value:
            raise Forbidden("Only an owner can change owner membership status")
        previous = member.status
        if previous == status:
            return member
        if status == "suspended" and member.role == TenantRole.OWNER.value:
            owner_count = session.scalar(
                select(func.count()).select_from(MembershipRecord).where(
                    MembershipRecord.tenant_id == tenant_id,
                    MembershipRecord.status == "active",
                    MembershipRecord.role == TenantRole.OWNER.value,
                )
            )
            if owner_count <= 1:
                raise Conflict("A tenant must keep at least one active owner")
        member.status = status
        member.suspended_at = now if status == "suspended" else None
        audit(session, tenant_id, actor.id, "tenant.member_status_changed", "user", str(member_id), {
            "from": previous, "to": status, "changed_at": now.isoformat(),
        })
    return member


def lock_tenant(session: Session, tenant_id: UUID) -> TenantRecord:
    tenant = session.scalar(
        select(TenantRecord).where(TenantRecord.id == tenant_id).with_for_update()
    )
    if tenant is None or tenant.status != "active":
        raise NotFound("Tenant not found")
    return tenant
