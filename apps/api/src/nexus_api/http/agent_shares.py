"""HTTP routes for sharing enterprise agents with shared spaces (openspec 2026-11-03, section 4).

Managing shares is for the owning enterprise's owner or admin. Members of a shared space read the agents
shared with their space through `/shared-agents`, and only see what their effective level allows.
Business rules live in `nexus_platform.shared_spaces.agent_shares`.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Response, status

from nexus_core.platform import Principal
from nexus_platform.shared_spaces import agent_shares as shares
from nexus_api.dependencies.platform import get_database_session, get_principal
from nexus_api.schemas.agent_shares import AgentShareCreate

router = APIRouter(prefix="/api/v1/tenants/{tenant_id}", tags=["Agent shares"])


@router.post("/agents/{agent_id}/shares", status_code=status.HTTP_201_CREATED)
def share_agent(tenant_id: UUID, agent_id: UUID, body: AgentShareCreate,
                principal: Principal = Depends(get_principal), db=Depends(get_database_session)):
    """Share the agent into a shared space at a level. Sharing again changes the level."""
    share = shares.share_agent(db, principal, tenant_id, agent_id, body.shared_space_id, body.level)
    return {"id": share.id, "agent_id": share.agent_id, "shared_space_id": share.shared_space_id,
            "level": share.level}


@router.get("/agents/{agent_id}/shares")
def list_agent_shares(tenant_id: UUID, agent_id: UUID, principal: Principal = Depends(get_principal),
                      db=Depends(get_database_session)):
    return shares.list_agent_shares(db, principal, tenant_id, agent_id)


@router.delete("/agents/{agent_id}/shares/{shared_space_id}", status_code=status.HTTP_204_NO_CONTENT)
def unshare_agent(tenant_id: UUID, agent_id: UUID, shared_space_id: UUID,
                  principal: Principal = Depends(get_principal), db=Depends(get_database_session)):
    shares.unshare_agent(db, principal, tenant_id, agent_id, shared_space_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/shared-agents")
def list_shared_agents(tenant_id: UUID, principal: Principal = Depends(get_principal),
                       db=Depends(get_database_session)):
    """Agents of other spaces shared with a shared space this space belongs to."""
    return shares.list_shared_agents(db, principal, tenant_id)


@router.get("/shared-agents/{agent_id}")
def get_shared_agent(tenant_id: UUID, agent_id: UUID, principal: Principal = Depends(get_principal),
                     db=Depends(get_database_session)):
    return shares.get_shared_agent(db, principal, tenant_id, agent_id)
