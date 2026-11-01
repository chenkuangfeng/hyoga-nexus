from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from nexus_core.platform import Principal, TenantRole, new_id, utc_now
from nexus_platform.errors import Conflict, Forbidden, NotFound
from nexus_platform.authz.audit import audit
from nexus_platform.orgs.access import SOURCE_ORGANIZATION, membership_is_active
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


def list_tenants(session: Session, principal: Principal) -> list[tuple[TenantRecord, str, bool]]:
    """Active spaces the user can enter, as (space, role, via_organization).

    `via_organization` is True when the user's access comes from an organization-sourced membership.
    """
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
        # Organization-sourced rows only list the space while the user is still in a bound subtree.
        return [(tenant, membership.role, membership.source == SOURCE_ORGANIZATION)
                for tenant, membership in rows if membership_is_active(session, membership)]


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
        if membership:
            membership.role = role.value
            membership.status = "active"
            membership.joined_at = now
            membership.revoked_at = None
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
        if member is None or member.status != "active":
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
        audit(session, tenant_id, actor.id, "tenant.member_removed", "user", str(member_id))


def lock_tenant(session: Session, tenant_id: UUID) -> TenantRecord:
    tenant = session.scalar(
        select(TenantRecord).where(TenantRecord.id == tenant_id).with_for_update()
    )
    if tenant is None or tenant.status != "active":
        raise NotFound("Tenant not found")
    return tenant
