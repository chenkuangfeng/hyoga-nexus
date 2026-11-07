"""System space: builtin skills and tools that every space can assign (openspec 2026-11-07-skill-evolution).

The system space is an ordinary ``tenants`` row of kind ``system``. It has no members, no code, cannot be signed
in to and is left out of every space list. Builtin tools and skills are registered under it, so the existing
resource registration, agent bindings and versions apply unchanged; ``authorize_resource`` lets any space use
them without a grant. "Effective in every space" means *assignable*: an agent still has to bind a resource, and
high-impact tool groups stay behind their own availability and agent switches.

A space administrator can switch one builtin resource off for that space only (``tenant_builtin_disabled``).
"""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus_core.native import BUILTIN_TOOL_NAMES
from nexus_core.platform import (
    GLOBAL_BUILTIN_KINDS, SYSTEM_TENANT_ID, SYSTEM_USER_ID, Principal, utc_now,
)
from nexus_platform.authz.audit import audit
from nexus_platform.authz.permissions import require_api_permission
from nexus_platform.authz.resources import register_resource
from nexus_platform.errors import InvalidConfiguration, NotFound
from nexus_platform.identity.service import require_membership, require_tenant, resolve_user
from nexus_platform.persistence.models import (
    PlatformResourceRecord, TenantBuiltinDisabledRecord, TenantRecord, UserRecord,
)

#: Version label of builtin tools; the tool registry has one version per tool.
BUILTIN_TOOL_VERSION = "v1"
#: Permission that manages the tool and skill catalog of a space.
MANAGE_PERMISSION = "tools:manage"


def ensure_system_tenant(session: Session) -> TenantRecord:
    """Create the system space and its reserved owner account when missing. Idempotent; needs an open transaction."""
    now = utc_now()
    user = session.get(UserRecord, SYSTEM_USER_ID)
    if user is None:
        user = UserRecord(id=SYSTEM_USER_ID, display_name="System", status="disabled", created_at=now)
        session.add(user)
        session.flush()
    tenant = session.get(TenantRecord, SYSTEM_TENANT_ID)
    if tenant is None:
        tenant = TenantRecord(id=SYSTEM_TENANT_ID, name="System", kind="system", status="active",
                              created_by=SYSTEM_USER_ID, created_at=now, updated_at=now)
        session.add(tenant)
        session.flush()
    return tenant


def sync_builtin_tools(session: Session) -> int:
    """Register every builtin tool under the system space. Returns how many were newly registered."""
    existing = set(session.scalars(select(PlatformResourceRecord.resource_id).where(
        PlatformResourceRecord.tenant_id == SYSTEM_TENANT_ID, PlatformResourceRecord.kind == "tool",
        PlatformResourceRecord.version_id == BUILTIN_TOOL_VERSION)))
    created = 0
    for name in BUILTIN_TOOL_NAMES:
        if name not in existing:
            register_resource(session, tenant_id=SYSTEM_TENANT_ID, kind="tool", resource_id=name,
                              version_id=BUILTIN_TOOL_VERSION)
            created += 1
    return created


def ensure_system_resources(session: Session) -> int:
    """Create the system space and sync builtin tools in one transaction. Safe to call at every start."""
    with session.begin():
        ensure_system_tenant(session)
        return sync_builtin_tools(session)


def disabled_builtins(session: Session, tenant_id: UUID) -> set[tuple[str, str]]:
    """``(kind, resource_id)`` pairs this space has switched off."""
    return {(row.kind, row.resource_id) for row in session.scalars(
        select(TenantBuiltinDisabledRecord).where(TenantBuiltinDisabledRecord.tenant_id == tenant_id))}


def is_builtin_disabled(session: Session, tenant_id: UUID, kind: str, resource_id: str) -> bool:
    return session.get(TenantBuiltinDisabledRecord, (tenant_id, kind, resource_id)) is not None


def _require_builtin(session: Session, kind: str, resource_id: str) -> None:
    if kind not in GLOBAL_BUILTIN_KINDS:
        raise InvalidConfiguration("builtin_kind_invalid")
    found = session.scalar(select(PlatformResourceRecord.id).where(
        PlatformResourceRecord.tenant_id == SYSTEM_TENANT_ID, PlatformResourceRecord.kind == kind,
        PlatformResourceRecord.resource_id == resource_id).limit(1))
    if found is None:
        raise NotFound("builtin_resource_not_found")


def list_disabled(session: Session, principal: Principal, tenant_id: UUID) -> list[dict[str, str]]:
    """Builtin resources switched off in this space. Any active member may read the list."""
    with session.begin():
        user = resolve_user(session, principal)
        require_tenant(session, tenant_id)
        require_membership(session, tenant_id, user.id)
        return [{"kind": kind, "resource_id": resource_id}
                for kind, resource_id in sorted(disabled_builtins(session, tenant_id))]


def disable_builtin(session: Session, principal: Principal, tenant_id: UUID, kind: str, resource_id: str) -> dict[str, str]:
    """Stop offering one builtin resource in this space. Needs ``tools:manage``; published agent versions keep it."""
    with session.begin():
        user = resolve_user(session, principal)
        require_tenant(session, tenant_id)
        require_membership(session, tenant_id, user.id)
        require_api_permission(session, tenant_id, user.id, MANAGE_PERMISSION)
        _require_builtin(session, kind, resource_id)
        if session.get(TenantBuiltinDisabledRecord, (tenant_id, kind, resource_id)) is None:
            session.add(TenantBuiltinDisabledRecord(tenant_id=tenant_id, kind=kind, resource_id=resource_id,
                                                    disabled_by=user.id, disabled_at=utc_now()))
            audit(session, tenant_id, user.id, "builtin.disabled", kind, resource_id)
        return {"kind": kind, "resource_id": resource_id, "disabled": "true"}


def enable_builtin_resource(session: Session, principal: Principal, tenant_id: UUID, kind: str, resource_id: str) -> dict[str, str]:
    """Offer a previously switched-off builtin resource again."""
    with session.begin():
        user = resolve_user(session, principal)
        require_tenant(session, tenant_id)
        require_membership(session, tenant_id, user.id)
        require_api_permission(session, tenant_id, user.id, MANAGE_PERMISSION)
        row = session.get(TenantBuiltinDisabledRecord, (tenant_id, kind, resource_id))
        if row is not None:
            session.delete(row)
            audit(session, tenant_id, user.id, "builtin.enabled", kind, resource_id)
        return {"kind": kind, "resource_id": resource_id, "disabled": "false"}
