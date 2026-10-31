"""Tenant role management and effective-permission resolution.

Effective access of an active member is the union of:
- the built-in full catalog, for owner and admin memberships;
- the menu and API grants of every custom role assigned to the member.
A member holding `roles:manage` may create and assign roles, but only grant permissions they
hold themselves, so role administration cannot escalate privileges.
"""
from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus_core.platform import Principal, TenantRole, new_id, utc_now
from nexus_platform.authz.audit import audit
from nexus_platform.authz.catalog import validate_grants
from nexus_platform.authz.permissions import EffectivePermissions, FULL_ACCESS, effective_permissions, require_api_permission
from nexus_platform.errors import Conflict, Forbidden, NotFound
from nexus_platform.identity.service import require_membership, require_tenant, resolve_user
from nexus_platform.persistence.models import (
    MembershipRecord,
    TenantAgentGrantRecord,
    TenantRoleApiGrantRecord,
    TenantRoleMenuGrantRecord,
    TenantRoleRecord,
    TenantUserRoleRecord,
)
from nexus_platform.tenants.service import lock_tenant


def require_role_manager(session: Session, principal: Principal, tenant_id: UUID) -> tuple[UUID, EffectivePermissions]:
    actor = resolve_user(session, principal)
    require_tenant(session, tenant_id)
    require_membership(session, tenant_id, actor.id)
    permissions = effective_permissions(session, tenant_id, actor.id)
    if not permissions.allows_api("roles:manage"):
        raise Forbidden("Your tenant role does not allow this action")
    return actor.id, permissions


def _ensure_within_actor(actor: EffectivePermissions, menus: frozenset[str], apis: frozenset[str]) -> None:
    if not (menus <= actor.menus and apis <= actor.apis):
        raise Forbidden("A role cannot grant permissions the actor does not hold")


def _write_grants(session: Session, role_id: UUID, menus: frozenset[str], apis: frozenset[str]) -> None:
    session.query(TenantRoleMenuGrantRecord).filter(TenantRoleMenuGrantRecord.role_id == role_id).delete()
    session.query(TenantRoleApiGrantRecord).filter(TenantRoleApiGrantRecord.role_id == role_id).delete()
    session.flush()
    session.add_all(TenantRoleMenuGrantRecord(role_id=role_id, menu=menu) for menu in sorted(menus))
    session.add_all(TenantRoleApiGrantRecord(role_id=role_id, permission=api) for api in sorted(apis))


def _role_in_tenant(session: Session, tenant_id: UUID, role_id: UUID) -> TenantRoleRecord:
    role = session.get(TenantRoleRecord, role_id)
    if role is None or role.tenant_id != tenant_id:
        raise NotFound("Tenant role not found")
    return role


def create_role(
    session: Session, principal: Principal, tenant_id: UUID, name: str, menus, apis
) -> TenantRoleRecord:
    name = name.strip()
    if not name:
        raise ValueError("Role name must not be empty")
    menu_set, api_set = validate_grants(menus, apis)
    now = utc_now()
    with session.begin():
        actor_id, actor = require_role_manager(session, principal, tenant_id)
        lock_tenant(session, tenant_id)
        _ensure_within_actor(actor, menu_set, api_set)
        if session.scalar(select(TenantRoleRecord.id).where(
            TenantRoleRecord.tenant_id == tenant_id, TenantRoleRecord.name == name
        )) is not None:
            raise Conflict("A role with this name already exists")
        role = TenantRoleRecord(id=new_id(), tenant_id=tenant_id, name=name, created_at=now, updated_at=now)
        session.add(role)
        session.flush()
        _write_grants(session, role.id, menu_set, api_set)
        audit(session, tenant_id, actor_id, "tenant.role_created", "role", str(role.id),
              {"menus": sorted(menu_set), "apis": sorted(api_set)})
    return role


def update_role_grants(
    session: Session, principal: Principal, tenant_id: UUID, role_id: UUID, menus, apis
) -> TenantRoleRecord:
    menu_set, api_set = validate_grants(menus, apis)
    with session.begin():
        actor_id, actor = require_role_manager(session, principal, tenant_id)
        lock_tenant(session, tenant_id)
        role = _role_in_tenant(session, tenant_id, role_id)
        _ensure_within_actor(actor, menu_set, api_set)
        _write_grants(session, role.id, menu_set, api_set)
        role.updated_at = utc_now()
        audit(session, tenant_id, actor_id, "tenant.role_updated", "role", str(role.id),
              {"menus": sorted(menu_set), "apis": sorted(api_set)})
    return role


def assign_role(session: Session, principal: Principal, tenant_id: UUID, member_id: UUID, role_id: UUID) -> None:
    with session.begin():
        actor_id, actor = require_role_manager(session, principal, tenant_id)
        lock_tenant(session, tenant_id)
        role = _role_in_tenant(session, tenant_id, role_id)
        member = session.get(MembershipRecord, (tenant_id, member_id))
        if member is None or member.status != "active":
            raise NotFound("Tenant member not found")
        if member.role in {TenantRole.OWNER.value, TenantRole.ADMIN.value}:
            raise Conflict("Owner and admin already have full access")
        grants = effective_permissions_for_role(session, role.id)
        _ensure_within_actor(actor, grants[0], grants[1])
        if session.get(TenantUserRoleRecord, (tenant_id, member_id, role.id)) is not None:
            raise Conflict("Role is already assigned to this member")
        session.add(TenantUserRoleRecord(
            tenant_id=tenant_id, user_id=member_id, role_id=role.id, assigned_at=utc_now()
        ))
        audit(session, tenant_id, actor_id, "tenant.role_assigned", "user", str(member_id),
              {"role_id": str(role.id)})


def unassign_role(session: Session, principal: Principal, tenant_id: UUID, member_id: UUID, role_id: UUID) -> None:
    with session.begin():
        actor_id, _ = require_role_manager(session, principal, tenant_id)
        lock_tenant(session, tenant_id)
        _role_in_tenant(session, tenant_id, role_id)
        assignment = session.get(TenantUserRoleRecord, (tenant_id, member_id, role_id))
        if assignment is None:
            raise NotFound("Role assignment not found")
        session.delete(assignment)
        audit(session, tenant_id, actor_id, "tenant.role_unassigned", "user", str(member_id),
              {"role_id": str(role_id)})


def effective_permissions_for_role(session: Session, role_id: UUID) -> tuple[frozenset[str], frozenset[str]]:
    """Return the menu and API grants stored on one role."""
    menus = frozenset(session.scalars(
        select(TenantRoleMenuGrantRecord.menu).where(TenantRoleMenuGrantRecord.role_id == role_id)
    ))
    apis = frozenset(session.scalars(
        select(TenantRoleApiGrantRecord.permission).where(TenantRoleApiGrantRecord.role_id == role_id)
    ))
    return menus, apis


def list_roles(session: Session, principal: Principal, tenant_id: UUID) -> list[dict]:
    with session.begin():
        require_role_manager(session, principal, tenant_id)
        roles = list(session.scalars(
            select(TenantRoleRecord).where(TenantRoleRecord.tenant_id == tenant_id).order_by(TenantRoleRecord.name)
        ))
        result = []
        for role in roles:
            menus, apis = effective_permissions_for_role(session, role.id)
            result.append({"role": role, "menus": sorted(menus), "apis": sorted(apis)})
    return result


def my_permissions(session: Session, principal: Principal, tenant_id: UUID) -> EffectivePermissions:
    with session.begin():
        actor = resolve_user(session, principal)
        require_tenant(session, tenant_id)
        require_membership(session, tenant_id, actor.id)
        return effective_permissions(session, tenant_id, actor.id)


__all__ = [
    "assign_role", "create_role", "list_agent_grants", "list_assignments", "list_roles", "my_permissions",
    "unassign_role",
    "update_role_grants",
]


def list_assignments(session: Session, principal: Principal, tenant_id: UUID) -> list[dict]:
    """Return active member-to-role assignments for a caller who may manage roles."""
    with session.begin():
        require_role_manager(session, principal, tenant_id)
        rows = session.execute(
            select(TenantUserRoleRecord.user_id, TenantUserRoleRecord.role_id)
            .join(MembershipRecord, (MembershipRecord.tenant_id == TenantUserRoleRecord.tenant_id)
                  & (MembershipRecord.user_id == TenantUserRoleRecord.user_id))
            .where(TenantUserRoleRecord.tenant_id == tenant_id, MembershipRecord.status == "active")
            .order_by(TenantUserRoleRecord.assigned_at)
        ).all()
    return [{"user_id": row[0], "role_id": row[1]} for row in rows]


def list_agent_grants(session: Session, principal: Principal, tenant_id: UUID) -> list[dict]:
    """Return role-to-agent grants of the tenant for a caller who may manage roles."""
    with session.begin():
        require_role_manager(session, principal, tenant_id)
        rows = session.execute(
            select(TenantAgentGrantRecord.role_id, TenantAgentGrantRecord.agent_id, TenantAgentGrantRecord.permission)
            .where(TenantAgentGrantRecord.tenant_id == tenant_id)
            .order_by(TenantAgentGrantRecord.agent_id, TenantAgentGrantRecord.permission)
        ).all()
    return [{"role_id": row[0], "agent_id": row[1], "permission": row[2]} for row in rows]
