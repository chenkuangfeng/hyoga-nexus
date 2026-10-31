"""Current membership/model/resource authority on the same session used for Run writes."""
from uuid import UUID
from nexus_core.platform import Principal
from nexus_platform.identity.repository import SqlAlchemyTenantAccess
from nexus_platform.identity.service import require_membership, require_tenant, resolve_user
from nexus_platform.models.provider_settings import authorize_model
from nexus_platform.authz.resources import authorize_resource
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
