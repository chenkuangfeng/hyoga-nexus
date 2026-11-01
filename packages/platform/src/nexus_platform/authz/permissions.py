"""Effective tenant permissions of a member: built-in full access for owner/admin, otherwise the
union of the menu and API grants of every role assigned to the member.

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


def effective_permissions(session: Session, tenant_id: UUID, user_id: UUID) -> EffectivePermissions:
    """Return the union of permissions for an active member; no membership yields no access."""
    membership = session.get(MembershipRecord, (tenant_id, user_id))
    if not membership_is_active(session, membership):
        return EffectivePermissions(frozenset(), frozenset())
    if membership.role in {TenantRole.OWNER.value, TenantRole.ADMIN.value}:
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
    return EffectivePermissions(frozenset(menus), frozenset(apis))


def require_api_permission(session: Session, tenant_id: UUID, user_id: UUID, permission: str) -> None:
    """Raise Forbidden unless the user's effective permissions include `permission`."""
    if not effective_permissions(session, tenant_id, user_id).allows_api(permission):
        raise Forbidden("Your tenant role does not allow this action")
