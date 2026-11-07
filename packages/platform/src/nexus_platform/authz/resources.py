"""Resource registration, explicit cross-tenant grants and per-call resource authorization."""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus_core.platform import GLOBAL_BUILTIN_KINDS, SYSTEM_TENANT_ID, Principal, new_id, utc_now
from nexus_platform.authz.audit import audit
from nexus_platform.errors import Forbidden, NotFound
from nexus_platform.identity.service import require_membership, require_tenant, resolve_user
from nexus_platform.persistence.models import PlatformResourceRecord, ResourceGrantRecord, TenantBuiltinDisabledRecord
from nexus_platform.tenants.service import ADMIN_ROLES


def register_resource(
    session: Session,
    *,
    tenant_id: UUID,
    kind: str,
    resource_id: str,
    version_id: str | None,
) -> PlatformResourceRecord:
    """Registration port called by a resource package after it owns/creates a version."""
    require_tenant(session, tenant_id)
    normalized_version = version_id or ""
    row = session.scalar(
        select(PlatformResourceRecord).where(
            PlatformResourceRecord.tenant_id == tenant_id,
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
        tenant_id=tenant_id,
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
    session: Session, *, tenant_id: UUID, kind: str, resource_id: str, version_id: str | None
) -> None:
    row = session.scalar(
        select(PlatformResourceRecord).where(
            PlatformResourceRecord.tenant_id == tenant_id,
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
    source_tenant_id: UUID,
    target_tenant_id: UUID,
    kind: str,
    resource_id: str,
    permissions: list[str],
) -> ResourceGrantRecord:
    if source_tenant_id == target_tenant_id:
        raise ValueError("A resource grant must target a different tenant")
    now = utc_now()
    with session.begin():
        actor = resolve_user(session, principal)
        require_tenant(session, source_tenant_id)
        require_tenant(session, target_tenant_id)
        require_membership(session, source_tenant_id, actor.id, roles=ADMIN_ROLES)
        source_resource = session.scalar(
            select(PlatformResourceRecord).where(
                PlatformResourceRecord.tenant_id == source_tenant_id,
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
                ResourceGrantRecord.source_tenant_id == source_tenant_id,
                ResourceGrantRecord.target_tenant_id == target_tenant_id,
                ResourceGrantRecord.kind == kind,
                ResourceGrantRecord.resource_id == resource_id,
            )
        )
        if grant is None:
            grant = ResourceGrantRecord(
                id=new_id(),
                source_tenant_id=source_tenant_id,
                target_tenant_id=target_tenant_id,
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
            source_tenant_id,
            actor.id,
            "resource.granted",
            kind,
            resource_id,
            {"target_tenant_id": str(target_tenant_id), "permissions": sorted(set(permissions))},
        )
    return grant


def revoke_resource_grant(session: Session, principal: Principal, grant_id: UUID) -> None:
    now = utc_now()
    with session.begin():
        actor = resolve_user(session, principal)
        grant = session.get(ResourceGrantRecord, grant_id)
        if grant is None or grant.revoked_at is not None:
            raise NotFound("Resource grant not found")
        require_membership(session, grant.source_tenant_id, actor.id, roles=ADMIN_ROLES)
        grant.revoked_at = now
        audit(session, grant.source_tenant_id, actor.id, "resource.grant_revoked", grant.kind, grant.resource_id)


def authorize_resource(
    session: Session,
    tenant_id: UUID,
    kind: str,
    resource_id: str,
    *,
    source_tenant_id: UUID | None = None,
    resource_version_id: str | None = None,
    permission: str = "use",
) -> PlatformResourceRecord:
    """Recheck resource status and current grant at the actual operation boundary.

    Builtin skills and tools (kinds in ``GLOBAL_BUILTIN_KINDS``) are registered under the system space and need no
    grant: every space may use them unless it has switched the resource off. A space-owned registration of the
    same name takes precedence, so bindings made before the system space existed keep working.
    """
    if kind in GLOBAL_BUILTIN_KINDS and source_tenant_id == SYSTEM_TENANT_ID:
        return _builtin_resource(session, tenant_id, kind, resource_id, resource_version_id)
    if source_tenant_id is None or source_tenant_id == tenant_id:
        direct = session.scalar(
            select(PlatformResourceRecord).where(
                PlatformResourceRecord.tenant_id == tenant_id,
                PlatformResourceRecord.kind == kind,
                PlatformResourceRecord.resource_id == resource_id,
                PlatformResourceRecord.version_id == (resource_version_id or ""),
                PlatformResourceRecord.active.is_(True),
            )
        )
        if direct is not None:
            return direct
        if kind in GLOBAL_BUILTIN_KINDS:
            builtin = _find_builtin(session, kind, resource_id, resource_version_id)
            if builtin is not None:
                return _builtin_resource(session, tenant_id, kind, resource_id, resource_version_id)
    shared = session.execute(
        select(PlatformResourceRecord, ResourceGrantRecord)
        .join(ResourceGrantRecord, ResourceGrantRecord.source_tenant_id == PlatformResourceRecord.tenant_id)
        .where(
            ResourceGrantRecord.target_tenant_id == tenant_id,
            *([ResourceGrantRecord.source_tenant_id == source_tenant_id] if source_tenant_id else []),
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


def _find_builtin(session: Session, kind: str, resource_id: str, version_id: str | None) -> PlatformResourceRecord | None:
    return session.scalar(
        select(PlatformResourceRecord).where(
            PlatformResourceRecord.tenant_id == SYSTEM_TENANT_ID,
            PlatformResourceRecord.kind == kind,
            PlatformResourceRecord.resource_id == resource_id,
            PlatformResourceRecord.version_id == (version_id or ""),
            PlatformResourceRecord.active.is_(True),
        )
    )


def _builtin_resource(session: Session, tenant_id: UUID, kind: str, resource_id: str,
                      version_id: str | None) -> PlatformResourceRecord:
    """The builtin registration, or Forbidden when it is missing, revoked or switched off in this space."""
    row = _find_builtin(session, kind, resource_id, version_id)
    if row is None:
        raise Forbidden("Resource is unavailable or its grant was revoked")
    if session.get(TenantBuiltinDisabledRecord, (tenant_id, kind, resource_id)) is not None:
        raise Forbidden("Resource is disabled in this space")
    return row
