"""Department and member audiences of agents and knowledge bases (openspec 2026-11-11-enterprise-saas E5).

- ``/api/v1/tenants/{tenant_id}/agents/{agent_id}/audience``: who may use the agent (its maintainers write).
- ``/api/v1/tenants/{tenant_id}/knowledge/bases/{kb_id}/audience``: who may read a ``scoped`` base (its managers
  write; setting a non-empty audience also sets ``visibility = 'scoped'``).

Writes replace the whole list. A change that would let an agent's users reach a base they cannot read is refused
(``binding_scope_narrower`` / ``kb_in_use``) and nothing is stored.
"""
from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus_api.dependencies.platform import get_database_session, get_principal
from nexus_core.platform import Principal
from nexus_platform.agents.access import can_maintain_agent
from nexus_platform.agents.service import check_binding_scope, get_agent
from nexus_platform.authz import audiences
from nexus_platform.errors import Forbidden
from nexus_platform.identity.service import require_membership, require_tenant, resolve_user
from nexus_platform.knowledge import access as kb_access
from nexus_platform.knowledge.service import recheck_agents
from nexus_platform.persistence.models import AgentAudienceRecord, KnowledgeBaseAudienceRecord

router = APIRouter(prefix='/api/v1/tenants/{tenant_id}', tags=['Audiences'])


class AudienceItem(BaseModel):
    kind: Literal['user', 'org_unit']
    id: UUID
    include_descendants: bool = True


class AudienceInput(BaseModel):
    items: list[AudienceItem] = Field(default_factory=list, max_length=500)


def _actor(db: Session, principal: Principal, tenant_id: UUID):
    user = resolve_user(db, principal)
    require_tenant(db, tenant_id)
    require_membership(db, tenant_id, user.id)
    return user


def _agent(db: Session, principal: Principal, tenant_id: UUID, agent_id: UUID):
    user = _actor(db, principal, tenant_id)
    agent, _ = get_agent(db, tenant_id, agent_id)
    if not can_maintain_agent(db, tenant_id, user.id, agent):
        raise Forbidden("Only the agent's maintainers can assign it")
    return user, agent


@router.get('/agents/{agent_id}/audience')
def get_agent_audience(tenant_id: UUID, agent_id: UUID, principal: Principal = Depends(get_principal),
                       db: Session = Depends(get_database_session)) -> dict[str, Any]:
    with db.begin():
        _, agent = _agent(db, principal, tenant_id, agent_id)
        rows = db.scalars(select(AgentAudienceRecord).where(AgentAudienceRecord.agent_id == agent.id)).all()
        return {'items': audiences.audience_view(rows)}


@router.put('/agents/{agent_id}/audience')
def set_agent_audience(tenant_id: UUID, agent_id: UUID, body: AudienceInput,
                       principal: Principal = Depends(get_principal),
                       db: Session = Depends(get_database_session)) -> dict[str, Any]:
    with db.begin():
        user, agent = _agent(db, principal, tenant_id, agent_id)
        items = audiences.replace(db, AgentAudienceRecord, 'agent_id', agent.id, tenant_id, user.id,
                                  [item.model_dump() for item in body.items], action='agent.audience_updated',
                                  target_type='agent')
        check_binding_scope(db, agent)
        return {'items': items}


@router.get('/knowledge/bases/{kb_id}/audience')
def get_base_audience(tenant_id: UUID, kb_id: UUID, principal: Principal = Depends(get_principal),
                      db: Session = Depends(get_database_session)) -> dict[str, Any]:
    with db.begin():
        user = _actor(db, principal, tenant_id)
        kb = kb_access.manageable_base(db, kb_id, tenant_id, user.id)
        rows = db.scalars(select(KnowledgeBaseAudienceRecord).where(KnowledgeBaseAudienceRecord.kb_id == kb.id)).all()
        return {'visibility': kb.visibility, 'items': audiences.audience_view(rows)}


@router.put('/knowledge/bases/{kb_id}/audience')
def set_base_audience(tenant_id: UUID, kb_id: UUID, body: AudienceInput, principal: Principal = Depends(get_principal),
                      db: Session = Depends(get_database_session)) -> dict[str, Any]:
    with db.begin():
        user = _actor(db, principal, tenant_id)
        kb = kb_access.manageable_base(db, kb_id, tenant_id, user.id)
        items = audiences.replace(db, KnowledgeBaseAudienceRecord, 'kb_id', kb.id, tenant_id, user.id,
                                  [item.model_dump() for item in body.items], action='knowledge_base.audience_updated',
                                  target_type='knowledge_base')
        if items and kb.visibility != kb_access.SCOPED:
            from nexus_platform.knowledge.service import update_base
            update_base(db, tenant_id, user.id, kb.id, {'visibility': kb_access.SCOPED})
        recheck_agents(db, kb)
        return {'visibility': kb.visibility, 'items': items}
