"""Enterprise administration of agents and knowledge bases (openspec 2026-11-11-enterprise-saas E0, decision 2).

Every route lives under ``/api/v1/tenants/{tenant_id}/admin``, the prefix reserved for the enterprise admin
console. Creation here always yields ``enterprise`` resources; the workspace routes (``/agents``,
``/knowledge/bases``) always yield ``personal`` ones. Permission checks stay in the platform services:

- creating enterprise agents / bases needs ``enterprise_agents:manage`` / ``enterprise_kbs:manage``;
- maintainers of an enterprise base are managed by whoever may manage the base;
- converting a member's personal agent or base needs an owner or admin.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from nexus_api.dependencies.platform import get_database_session, get_principal
from nexus_api.http.knowledge import BaseInput, _user
from nexus_api.http.platform import agent_view, bindings_data
from nexus_api.schemas.platform import AgentDraftInput, AgentView
from nexus_core.platform import Principal
from nexus_platform.agents import service as agents
from nexus_platform.agents.access import ENTERPRISE
from nexus_platform.knowledge import ownership, service as knowledge

router = APIRouter(prefix='/api/v1/tenants/{tenant_id}/admin', tags=['Enterprise administration'])


class MaintainerInput(BaseModel):
    user_id: UUID


@router.post('/agents', response_model=AgentView, status_code=status.HTTP_201_CREATED)
def create_enterprise_agent(tenant_id: UUID, body: AgentDraftInput, principal: Principal = Depends(get_principal),
                            db: Session = Depends(get_database_session)):
    """Create an enterprise agent: maintained only by enterprise agent managers, assigned to members for use."""
    row = agents.create_agent(
        db, principal, tenant_id, name=body.name, description=body.description,
        runtime_type=body.runtime_type, instructions=body.instructions,
        model_profile_version_id=body.model_profile_version_id, budgets=body.budgets,
        bindings=bindings_data(body.resource_bindings, tenant_id), ownership=ENTERPRISE,
    )
    _, binding_rows = agents.get_agent(db, tenant_id, row.id)
    return agent_view(row, binding_rows, user_id=row.created_by, can_maintain=True)


@router.post('/agents/{agent_id}/convert-to-enterprise', response_model=AgentView)
def convert_agent(tenant_id: UUID, agent_id: UUID, principal: Principal = Depends(get_principal),
                  db: Session = Depends(get_database_session)):
    """Turn a member's personal agent into an enterprise agent (owner or admin)."""
    agents.convert_agent_to_enterprise(db, principal, tenant_id, agent_id)
    with db.begin():
        row, bindings = agents.get_agent(db, tenant_id, agent_id)
        from nexus_platform.agents.access import can_maintain_agent
        from nexus_platform.identity.service import resolve_user
        user_id = resolve_user(db, principal).id
        maintains = can_maintain_agent(db, tenant_id, user_id, row)
    return agent_view(row, bindings, user_id=user_id, can_maintain=maintains)


@router.post('/knowledge/bases', status_code=status.HTTP_201_CREATED)
def create_enterprise_base(tenant_id: UUID, body: BaseInput, principal: Principal = Depends(get_principal),
                           db: Session = Depends(get_database_session)) -> dict[str, Any]:
    """Create an enterprise knowledge base; its content may also be maintained by named maintainers."""
    with db.begin():
        user = _user(db, principal, tenant_id)
        kb = knowledge.create_base(
            db, tenant_id, user.id, name=body.name, description=body.description, kb_type=body.type,
            indexing=body.indexing_strategy, vector_store_id=body.vector_store_id,
            storage_backend_id=body.storage_backend_id, embedding_model_id=body.embedding_model_id,
            chunk_size=body.chunking_config.chunk_size, chunk_overlap=body.chunking_config.chunk_overlap,
            settings=body.settings, ownership=ENTERPRISE)
    return knowledge.base_view(db, kb, tenant_id, user.id)


@router.post('/knowledge/bases/{kb_id}/convert-to-enterprise')
def convert_base(tenant_id: UUID, kb_id: UUID, principal: Principal = Depends(get_principal),
                 db: Session = Depends(get_database_session)) -> dict[str, Any]:
    """Turn a member's personal knowledge base into an enterprise base (owner or admin)."""
    with db.begin():
        user = _user(db, principal, tenant_id)
        kb = ownership.convert_to_enterprise(db, tenant_id, user.id, kb_id)
    return knowledge.base_view(db, kb, tenant_id, user.id)


@router.get('/knowledge/bases/{kb_id}/maintainers')
def list_maintainers(tenant_id: UUID, kb_id: UUID, principal: Principal = Depends(get_principal),
                     db: Session = Depends(get_database_session)) -> dict[str, Any]:
    with db.begin():
        user = _user(db, principal, tenant_id)
        return {'items': ownership.list_maintainers(db, tenant_id, user.id, kb_id)}


@router.post('/knowledge/bases/{kb_id}/maintainers', status_code=status.HTTP_201_CREATED)
def add_maintainer(tenant_id: UUID, kb_id: UUID, body: MaintainerInput, principal: Principal = Depends(get_principal),
                   db: Session = Depends(get_database_session)) -> dict[str, Any]:
    with db.begin():
        user = _user(db, principal, tenant_id)
        return {'items': ownership.add_maintainer(db, tenant_id, user.id, kb_id, body.user_id)}


@router.delete('/knowledge/bases/{kb_id}/maintainers/{user_id}', status_code=status.HTTP_204_NO_CONTENT)
def remove_maintainer(tenant_id: UUID, kb_id: UUID, user_id: UUID, principal: Principal = Depends(get_principal),
                      db: Session = Depends(get_database_session)) -> Response:
    with db.begin():
        actor = _user(db, principal, tenant_id)
        ownership.remove_maintainer(db, tenant_id, actor.id, kb_id, user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
