"""Built-in enterprise roles (openspec 2026-11-11-enterprise-saas decision 8).

Every enterprise gets ``security_admin`` (enterprise policy, tool risk settings, audit) and ``auditor`` (audit
metadata only). They are ordinary roles with ``builtin = true``: assignable to members, but their name and
grants cannot be changed. Kept free of service imports so tenant creation paths can call it.
"""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus_core.platform import new_id, utc_now
from nexus_platform.persistence.models import TenantRoleApiGrantRecord, TenantRoleMenuGrantRecord, TenantRoleRecord

BUILTIN_ROLES: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "security_admin": (("audit",), ("policy:manage", "tools:manage", "audit:read")),
    "auditor": (("audit",), ("audit:read",)),
}


def ensure_builtin_roles(session: Session, tenant_id: UUID) -> None:
    """Create the missing built-in roles of one enterprise inside the caller's transaction."""
    now = utc_now()
    for name, (menus, apis) in BUILTIN_ROLES.items():
        existing = session.scalar(select(TenantRoleRecord).where(
            TenantRoleRecord.tenant_id == tenant_id, TenantRoleRecord.name == name))
        if existing is not None:
            existing.builtin = True
            continue
        role = TenantRoleRecord(id=new_id(), tenant_id=tenant_id, name=name, builtin=True,
                                created_at=now, updated_at=now)
        session.add(role)
        session.flush()
        session.add_all(TenantRoleMenuGrantRecord(role_id=role.id, menu=menu) for menu in menus)
        session.add_all(TenantRoleApiGrantRecord(role_id=role.id, permission=api) for api in apis)
