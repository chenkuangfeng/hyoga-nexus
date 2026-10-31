from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session, sessionmaker

from nexus_core.platform import Principal, ResourceReference
from nexus_platform.runs.service import authorize_run_resource


class SqlAlchemyResourceAuthorization:
    """Runtime-facing adapter over the platform's current-grant check."""

    def __init__(self, sessions: sessionmaker[Session]):
        self._sessions = sessions

    def authorize(
        self,
        principal: Principal,
        tenant_id: UUID,
        run_id: UUID,
        binding_id: UUID,
        permission: str = "use",
    ) -> ResourceReference:
        with self._sessions() as session:
            resource = authorize_run_resource(
                session, principal, tenant_id, run_id, binding_id, permission=permission
            )
            return ResourceReference(
                kind=resource.kind,
                resource_id=resource.resource_id,
                version_id=resource.version_id or None,
            )
