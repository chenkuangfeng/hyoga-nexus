"""Run access: one application responsibility with legacy function compatibility."""
from __future__ import annotations
from nexus_platform.persistence.unit_of_work import SqlAlchemyUnitOfWork
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.orm import Session
from nexus_core.platform import Principal, RunStatus
from nexus_platform.errors import Conflict, Forbidden, NotFound
from nexus_platform.identity.service import require_membership, require_tenant, resolve_user
from nexus_platform.persistence.models import ResourceBindingRecord, RunRecord
from nexus_platform.authz.audit import audit
from nexus_platform.authz.resources import authorize_resource

def authorize_run_resource(session: Session, principal: Principal, tenant_id: UUID, run_id: UUID, binding_id: UUID, *, permission: str='use'):
    return RunResourceAccessService(SqlAlchemyUnitOfWork(session)).authorize(principal, tenant_id, run_id, binding_id, permission=permission)

class RunResourceAccessService:
    """Own the access application operation and its transaction boundary."""

    def __init__(self, unit_of_work: SqlAlchemyUnitOfWork):
        self.unit_of_work = unit_of_work

    def authorize(
        self,
        principal: Principal,
        tenant_id: UUID,
        run_id: UUID,
        binding_id: UUID,
        *,
        permission: str = "use",
    ):
        """Permission port for a Runtime/tool adapter; validates the current grant at call time."""
        with self.unit_of_work as work:
            session = work.session
            user = resolve_user(session, principal)
            require_tenant(session, tenant_id)
            require_membership(session, tenant_id, user.id)
            run = session.scalar(
                select(RunRecord).where(
                    RunRecord.id == run_id,
                    RunRecord.tenant_id == tenant_id,
                    RunRecord.principal_id == user.id,
                ).with_for_update()
            )
            if run is None:
                raise NotFound("Run not found")
            if run.status != RunStatus.RUNNING.value:
                raise Conflict("Resources may only be accessed while a Run is running")
            binding = session.scalar(
                select(ResourceBindingRecord).where(
                    ResourceBindingRecord.id == binding_id,
                    ResourceBindingRecord.agent_version_id == UUID(run.config_snapshot["agent_version_id"]),
                )
            )
            if binding is None or binding.binding_config.get("enabled") is False:
                raise Forbidden("Resource is not bound or enabled for this Run")
            resource = authorize_resource(
                session, tenant_id, binding.kind, binding.resource_id,
                source_tenant_id=binding.source_tenant_id,
                resource_version_id=binding.resource_version_id,
                permission=permission,
            )
            audit(session, tenant_id, user.id, "run.resource_access", binding.kind, binding.resource_id,
                  {"run_id": str(run.id), "permission": permission})
            return resource
