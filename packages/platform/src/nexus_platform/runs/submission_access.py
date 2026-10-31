"""Current membership/model/resource authority on the same session used for Run writes."""
from uuid import UUID
from nexus_core.platform import Principal
from nexus_platform.identity.repository import SqlAlchemyTenantAccess
from nexus_platform.identity.service import require_membership, require_tenant, resolve_user
from nexus_platform.models.provider_settings import authorize_model
from nexus_platform.authz.resources import authorize_resource
from nexus_platform.agents.access import require_agent_permission
from nexus_platform.errors import NotFound
from nexus_platform.persistence.models import AgentRecord
from sqlalchemy import select
from .configuration import AuthorizedMember, BoundResource


class SqlAlchemySubmissionAccess(SqlAlchemyTenantAccess):
    """Adapt existing authority checks; snapshots never replace live grants or user status."""
    def require_member(self, principal: Principal, tenant_id: UUID) -> AuthorizedMember:
        user = resolve_user(self.session, principal)
        require_tenant(self.session, tenant_id)
        membership = require_membership(self.session, tenant_id, user.id)
        return AuthorizedMember(user.id, membership.role)

    def require_resource(self, tenant_id: UUID, binding: BoundResource) -> None:
        authorize_resource(
            self.session, tenant_id, binding.kind, binding.resource_id,
            source_tenant_id=binding.source_tenant_id,
            resource_version_id=binding.resource_version_id, permission='use',
        )

    def require_model(self, tenant_id: UUID, user_id: UUID, version_id: UUID) -> None:
        authorize_model(self.session, tenant_id, user_id, version_id)

    def require_agent_run(self, tenant_id: UUID, user_id: UUID, agent_id: UUID) -> None:
        """Re-check the run permission on every submission so revoked grants stop new Runs."""
        agent = self.session.scalar(select(AgentRecord).where(
            AgentRecord.id == agent_id, AgentRecord.tenant_id == tenant_id
        ))
        if agent is None:
            raise NotFound("Agent not found")
        require_agent_permission(self.session, tenant_id, user_id, agent, "run")
