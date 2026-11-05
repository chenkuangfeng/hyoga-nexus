"""Agent editor endpoints: tool catalog, archive (soft delete) and copy.

Reference: WeKnora ``GET /agents/tools``, ``DELETE /agents/:id`` and ``POST /agents/:id/copy``
(``internal/handler/custom_agent.go``), rewritten for Nexus spaces, drafts and grants
(openspec ``2026-11-05-weknora-agent-tool-model-settings``).
"""
from __future__ import annotations

from dataclasses import asdict
from uuid import UUID

from fastapi import APIRouter, Depends, status
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus_api.dependencies.platform import get_database_session, get_principal
from nexus_api.http.platform import agent_view
from nexus_api.schemas.platform import AgentView
from nexus_core.platform import Principal
from nexus_platform.agents import service as agents
from nexus_platform.identity.service import require_membership, require_tenant, resolve_user
from nexus_platform.persistence.models import PlatformResourceRecord
from nexus_platform.tenants.service import ADMIN_ROLES

router = APIRouter(prefix="/api/v1/tenants/{tenant_id}", tags=["Agent editor"])


class AgentCopyInput(BaseModel):
    """Optional name of the copy; defaults to the source name with a copy suffix."""

    name: str | None = Field(default=None, max_length=160)


@router.get("/agent-tools")
def agent_tools(tenant_id: UUID, principal: Principal = Depends(get_principal),
                db: Session = Depends(get_database_session)):
    """Return the builtin tools an agent may bind, with the space's enablement state.

    Any member may read the catalog; non-members get 404. ``enabled_in_tenant`` reflects the space's
    active tool resources (``POST .../tools/{name}/enable``). ``default_tools`` is the caller's Native
    preference for new agents. Listing a tool grants nothing: binding and per-call checks still apply.
    """
    from nexus_tools.builtins.catalog import GROUP_ORDER, builtin_catalog
    from nexus_platform.runs.settings import view as native_preferences
    with db.begin():
        user = resolve_user(db, principal)
        require_tenant(db, tenant_id)
        membership = require_membership(db, tenant_id, user.id)
        enabled = set(db.scalars(select(PlatformResourceRecord.resource_id).where(
            PlatformResourceRecord.tenant_id == tenant_id, PlatformResourceRecord.kind == "tool",
            PlatformResourceRecord.version_id == "v1", PlatformResourceRecord.active.is_(True))))
        default_tools = list(native_preferences(db, user.id, tenant_id)["settings"]["behavior"]["enabled_tools"])
    return {
        "tools": [asdict(entry) | {"enabled_in_tenant": entry.name in enabled} for entry in builtin_catalog()],
        "groups": list(GROUP_ORDER),
        "default_tools": default_tools,
        "can_enable_tools": membership.role in ADMIN_ROLES,
    }


@router.delete("/agents/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
def archive_agent(tenant_id: UUID, agent_id: UUID, principal: Principal = Depends(get_principal),
                  db: Session = Depends(get_database_session)) -> Response:
    """Archive an agent: hidden from lists and new sessions; existing session history stays readable."""
    agents.archive_agent(db, principal, tenant_id, agent_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/agents/{agent_id}/copy", response_model=AgentView, status_code=status.HTTP_201_CREATED)
def copy_agent(tenant_id: UUID, agent_id: UUID, body: AgentCopyInput | None = None,
               principal: Principal = Depends(get_principal), db: Session = Depends(get_database_session)):
    """Copy the agent's draft into a new unpublished agent; shares and versions are not copied."""
    if body is not None and body.name and body.name.strip():
        name = body.name.strip()
    else:
        with db.begin():
            source, _ = agents.get_agent(db, tenant_id, agent_id)
            name = f"{source.name} (copy)"
    row = agents.copy_agent(db, principal, tenant_id, agent_id, name=name)
    _, bindings = agents.get_agent(db, tenant_id, row.id)
    return agent_view(row, bindings)
