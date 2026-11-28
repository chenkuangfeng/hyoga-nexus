"""Request-local bulk equivalent of resources.authorize_resource.

Reads current registrations, grants and builtin disables once per name batch. This object must
never be cached across requests. Actual resource executions continue using the scalar port.
"""
from __future__ import annotations

from uuid import UUID
from collections.abc import Iterable
from sqlalchemy.orm import Session
from sqlalchemy import select

from nexus_core.platform import GLOBAL_BUILTIN_KINDS, SYSTEM_TENANT_ID
from nexus_platform.errors import Forbidden
from nexus_platform.persistence.models import PlatformResourceRecord, ResourceGrantRecord, TenantBuiltinDisabledRecord


class ResourceAuthorizationBatch:
    """Materialize only named resource facts, preserving local/builtin/shared precedence."""

    def __init__(self, db: Session, tenant_id: UUID,
                 requests: Iterable[tuple[str, str, UUID | None, str | None]]) -> None:
        self.tenant_id = tenant_id
        self.resources, self.grants, self.disabled = {}, [], set()
        requests = tuple(requests)
        names = sorted({r[1] for r in requests})
        sources = {tenant_id, SYSTEM_TENANT_ID} | {r[2] for r in requests if r[2]}
        for start in range(0, len(names), 300):
            batch = names[start:start + 300]
            grants = list(db.scalars(select(ResourceGrantRecord).where(
                ResourceGrantRecord.target_tenant_id == tenant_id, ResourceGrantRecord.resource_id.in_(batch),
                ResourceGrantRecord.revoked_at.is_(None))))
            self.grants.extend(grants)
            sources.update(g.source_tenant_id for g in grants)
        for start in range(0, len(names), 300):
            batch = names[start:start + 300]
            # Source UUIDs are literals in one IN; normal runs have only a handful of resource spaces.
            rows = db.scalars(select(PlatformResourceRecord).where(
                PlatformResourceRecord.resource_id.in_(batch), PlatformResourceRecord.active.is_(True),
                PlatformResourceRecord.tenant_id.in_(sources)))
            self.resources.update({(r.tenant_id, r.kind, r.resource_id, r.version_id): r for r in rows})
            self.disabled.update((r.kind, r.resource_id) for r in db.scalars(select(TenantBuiltinDisabledRecord).where(
                TenantBuiltinDisabledRecord.tenant_id == tenant_id, TenantBuiltinDisabledRecord.resource_id.in_(batch))))

    def authorize(self, kind: str, resource_id: str, source_tenant_id: UUID | None = None,
                  resource_version_id: str | None = None, permission: str = 'use') -> PlatformResourceRecord:
        """Return the same eligible registration as scalar authorization, or fail closed."""
        version = resource_version_id or ''
        builtin_kind = kind in GLOBAL_BUILTIN_KINDS
        if not (builtin_kind and source_tenant_id == SYSTEM_TENANT_ID):
            if source_tenant_id is None or source_tenant_id == self.tenant_id:
                direct = self.resources.get((self.tenant_id, kind, resource_id, version))
                if direct is not None:
                    return direct
        if builtin_kind and source_tenant_id in (None, self.tenant_id, SYSTEM_TENANT_ID):
            builtin = self.resources.get((SYSTEM_TENANT_ID, kind, resource_id, version))
            if builtin is not None:
                if (kind, resource_id) in self.disabled:
                    raise Forbidden('Resource is disabled in this space')
                return builtin
            if source_tenant_id == SYSTEM_TENANT_ID:
                raise Forbidden('Resource is unavailable or its grant was revoked')
        for grant in self.grants:
            if (grant.kind == kind and grant.resource_id == resource_id and permission in grant.permissions
                    and (source_tenant_id is None or grant.source_tenant_id == source_tenant_id)):
                resource = self.resources.get((grant.source_tenant_id, kind, resource_id, version))
                if resource is not None:
                    return resource
        raise Forbidden('Resource is unavailable or its grant was revoked')
