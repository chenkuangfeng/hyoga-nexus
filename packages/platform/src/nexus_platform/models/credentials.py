from __future__ import annotations

import re
from urllib.parse import urlsplit
from uuid import UUID

from sqlalchemy.orm import Session

from nexus_core.platform import Principal, new_id, utc_now
from nexus_platform.identity.service import require_membership, require_tenant, resolve_user
from nexus_platform.authz.permissions import require_api_permission
from nexus_platform.persistence.models import CredentialReferenceRecord
from nexus_platform.tenants.service import ADMIN_ROLES
from nexus_platform.authz.audit import audit


ALLOWED_BACKENDS = {"vault", "environment", "keyring", "external"}
EXPECTED_SCHEMES = {
    "vault": "vault://",
    "environment": "env://",
    "keyring": "keyring://",
    "external": "secret://",
}


def create_credential_reference(
    session: Session, principal: Principal, tenant_id: UUID, *, backend: str, handle: str
) -> CredentialReferenceRecord:
    backend = backend.strip().casefold()
    handle = handle.strip()
    if backend not in ALLOWED_BACKENDS:
        raise ValueError("Unsupported credential reference backend")
    if not handle.startswith(EXPECTED_SCHEMES[backend]) or len(handle) <= len(EXPECTED_SCHEMES[backend]):
        raise ValueError(f"Credential handle must use the {EXPECTED_SCHEMES[backend]} reference scheme")
    parsed = urlsplit(handle)
    if parsed.username or parsed.password or parsed.query or parsed.fragment or any(ch.isspace() for ch in handle):
        raise ValueError("Credential handle must be an opaque reference without user info, query, or whitespace")
    if re.search(r"(?i)(?:sk-[a-z0-9]{20,}|bearer\s+\S+|(?:api[_-]?key|password|token)\s*[:=]\s*\S+)", handle):
        raise ValueError("Credential handle cannot contain a credential value")
    now = utc_now()
    with session.begin():
        user = resolve_user(session, principal)
        require_tenant(session, tenant_id)
        require_membership(session, tenant_id, user.id)
        require_api_permission(session, tenant_id, user.id, "models:manage")
        row = CredentialReferenceRecord(
            id=new_id(), tenant_id=tenant_id, backend=backend, handle=handle,
            scope={"tenant_id": str(tenant_id)}, status="active", created_at=now,
        )
        session.add(row)
        audit(session, tenant_id, user.id, "credential_reference.created", "credential_reference", str(row.id),
              {"backend": backend})
    return row
