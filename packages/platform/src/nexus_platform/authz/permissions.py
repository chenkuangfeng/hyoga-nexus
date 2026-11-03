"""Effective tenant permissions of a member.

- Owner: built-in full access.
- Admin: built-in access to everything except the governance keys in `GOVERNANCE_APIS`
  (organization tree, member administration, role administration, audit). Those are granted only
  through a custom role, as in openspec 2026-11-03-enterprise-personal-spaces section 4.
- Other members: the union of the menu and API grants of every role assigned to them.

Kept free of tenant-service imports so tenant, model and run services can all depend on it.
"""
from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus_core.platform import TenantRole
from nexus_platform.authz.catalog import API_PERMISSIONS, MENUS
from nexus_platform.errors import Forbidden
from nexus_platform.orgs.access import membership_is_active
from nexus_platform.persistence.models import (
    MembershipRecord,
    TenantRoleApiGrantRecord,
    TenantRoleMenuGrantRecord,
    TenantUserRoleRecord,
)


@dataclass(frozen=True)
class EffectivePermissions:
    menus: frozenset[str]
    apis: frozenset[str]

    def allows_api(self, permission: str) -> bool:
        return permission in self.apis


FULL_ACCESS = EffectivePermissions(MENUS, API_PERMISSIONS)

# Keys an admin does not hold by default; they come only from a custom role assigned to the admin.
GOVERNANCE_APIS = frozenset({"org:manage", "members:manage", "roles:manage", "audit:read"})
ADMIN_BASELINE = EffectivePermissions(MENUS, API_PERMISSIONS - GOVERNANCE_APIS)


def effective_permissions(session: Session, tenant_id: UUID, user_id: UUID) -> EffectivePermissions:
    """Return the union of permissions for an active member; no membership yields no access."""
    membership = session.get(MembershipRecord, (tenant_id, user_id))
    if not membership_is_active(session, membership):
        return EffectivePermissions(frozenset(), frozenset())
    if membership.role == TenantRole.OWNER.value:
        return FULL_ACCESS
    role_ids = select(TenantUserRoleRecord.role_id).where(
        TenantUserRoleRecord.tenant_id == tenant_id, TenantUserRoleRecord.user_id == user_id
    )
    menus = set(session.scalars(
        select(TenantRoleMenuGrantRecord.menu).where(TenantRoleMenuGrantRecord.role_id.in_(role_ids))
    ))
    apis = set(session.scalars(
        select(TenantRoleApiGrantRecord.permission).where(TenantRoleApiGrantRecord.role_id.in_(role_ids))
    ))
    if membership.role == TenantRole.ADMIN.value:
        menus |= ADMIN_BASELINE.menus
        apis |= ADMIN_BASELINE.apis
    return EffectivePermissions(frozenset(menus), frozenset(apis))


def require_api_permission(session: Session, tenant_id: UUID, user_id: UUID, permission: str) -> None:
    """Raise Forbidden unless the user's effective permissions include `permission`."""
    if not effective_permissions(session, tenant_id, user_id).allows_api(permission):
        raise Forbidden("Your tenant role does not allow this action")
