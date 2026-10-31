from __future__ import annotations

import re
from urllib.parse import urlsplit
from uuid import UUID

from sqlalchemy.orm import Session

from nexus_core.platform import Principal, new_id, utc_now
from nexus_platform.identity.service import require_membership, require_workspace, resolve_user
from nexus_platform.persistence.models import CredentialReferenceRecord
from nexus_platform.workspaces.service import ADMIN_ROLES
from nexus_platform.authz.audit import audit


ALLOWED_BACKENDS = {"vault", "environment", "keyring", "external"}
EXPECTED_SCHEMES = {
    "vault": "vault://",
    "environment": "env://",
    "keyring": "keyring://",
    "external": "secret://",
}


def create_credential_reference(
    session: Session, principal: Principal, workspace_id: UUID, *, backend: str, handle: str
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
        require_workspace(session, workspace_id)
        require_membership(session, workspace_id, user.id, roles=ADMIN_ROLES)
        row = CredentialReferenceRecord(
            id=new_id(), workspace_id=workspace_id, backend=backend, handle=handle,
            scope={"workspace_id": str(workspace_id)}, status="active", created_at=now,
        )
        session.add(row)
        audit(session, workspace_id, user.id, "credential_reference.created", "credential_reference", str(row.id),
              {"backend": backend})
    return row
