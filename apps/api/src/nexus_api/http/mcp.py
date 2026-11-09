"""MCP service management endpoints (openspec 2026-11-08-mcp, task 1.7).

CRUD, discovery and per-tool enablement are administrator capabilities (``tools:manage``); listing
is available to every active member. Connection config returns credential-reference markers, never
resolved secrets.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from nexus_core.platform import Principal
from nexus_platform.mcp import service as mcp
from nexus_api.dependencies.platform import get_database_session, get_principal

router = APIRouter(prefix="/api/v1")


class McpServiceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    description: str = Field(default="", max_length=4000)
    transport: str = Field(pattern="^(stdio|streamable_http|sse)$")
    config: dict[str, Any] = Field(default_factory=dict)


class McpServiceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    description: str | None = Field(default=None, max_length=4000)
    transport: str | None = Field(default=None, pattern="^(stdio|streamable_http|sse)$")
    config: dict[str, Any] | None = None
    enabled: bool | None = None


class EnabledToolsRequest(BaseModel):
    tools: list[str] = Field(default_factory=list, max_length=1000)


class ToolPolicyRequest(BaseModel):
    explicit_risk: str | None = Field(default=None, pattern="^(read|write|destructive)$")
    require_approval: bool = False
    confirm_downgrade: bool = False


@router.get("/tenants/{tenant_id}/mcp-services")
def list_mcp_services(tenant_id: UUID, principal: Principal = Depends(get_principal),
                      db: Session = Depends(get_database_session)) -> list[dict[str, Any]]:
    """Every MCP service in this Tenant. Requires active membership."""
    return mcp.list_services(db, principal, tenant_id)


@router.post("/tenants/{tenant_id}/mcp-services", status_code=201)
def create_mcp_service(tenant_id: UUID, body: McpServiceCreate, principal: Principal = Depends(get_principal),
                       db: Session = Depends(get_database_session)) -> dict[str, Any]:
    """Create a service. Requires the tools-management permission (administrators)."""
    return mcp.create_service(db, principal, tenant_id, name=body.name, description=body.description,
                              transport=body.transport, config=body.config)


@router.get("/tenants/{tenant_id}/mcp-services/{service_id}")
def get_mcp_service(tenant_id: UUID, service_id: UUID, principal: Principal = Depends(get_principal),
                    db: Session = Depends(get_database_session)) -> dict[str, Any]:
    return mcp.get_service(db, principal, tenant_id, service_id)


@router.patch("/tenants/{tenant_id}/mcp-services/{service_id}")
def update_mcp_service(tenant_id: UUID, service_id: UUID, body: McpServiceUpdate,
                       principal: Principal = Depends(get_principal),
                       db: Session = Depends(get_database_session)) -> dict[str, Any]:
    """Update a service; a connection-parameter change invalidates cached tools. Administrators."""
    return mcp.update_service(db, principal, tenant_id, service_id, name=body.name, description=body.description,
                              transport=body.transport, config=body.config, enabled=body.enabled)


@router.delete("/tenants/{tenant_id}/mcp-services/{service_id}", status_code=204)
def delete_mcp_service(tenant_id: UUID, service_id: UUID, principal: Principal = Depends(get_principal),
                       db: Session = Depends(get_database_session)) -> None:
    mcp.delete_service(db, principal, tenant_id, service_id)


@router.post("/tenants/{tenant_id}/mcp-services/{service_id}/discover")
def discover_mcp_service(tenant_id: UUID, service_id: UUID, timeout: float = Query(default=30.0, gt=0, le=300),
                         principal: Principal = Depends(get_principal),
                         db: Session = Depends(get_database_session)) -> dict[str, Any]:
    """List the service's tools and refresh the cached catalog (all newly discovered tools disabled)."""
    return mcp.discover_tools(db, principal, tenant_id, service_id, timeout=timeout)


@router.get("/tenants/{tenant_id}/mcp-services/{service_id}/tools")
def list_mcp_tools(tenant_id: UUID, service_id: UUID, principal: Principal = Depends(get_principal),
                   db: Session = Depends(get_database_session)) -> list[dict[str, Any]]:
    """Cached tool catalog with enablement and effective risk. Requires active membership."""
    return mcp.list_tools(db, principal, tenant_id, service_id)


@router.put("/tenants/{tenant_id}/mcp-services/{service_id}/enabled-tools")
def set_enabled_tools(tenant_id: UUID, service_id: UUID, body: EnabledToolsRequest,
                      principal: Principal = Depends(get_principal),
                      db: Session = Depends(get_database_session)) -> list[str]:
    """Replace the enable whitelist; only discovered tool names are accepted. Administrators."""
    return mcp.set_enabled_tools(db, principal, tenant_id, service_id, body.tools)


@router.put("/tenants/{tenant_id}/mcp-services/{service_id}/tools/{tool_name}/policy")
def set_tool_policy(tenant_id: UUID, service_id: UUID, tool_name: str, body: ToolPolicyRequest,
                    principal: Principal = Depends(get_principal),
                    db: Session = Depends(get_database_session)) -> dict[str, Any]:
    """Set a tool's explicit risk and approval requirement. Administrators."""
    return mcp.set_tool_policy(db, principal, tenant_id, service_id, tool_name,
                               explicit_risk=body.explicit_risk, require_approval=body.require_approval,
                               confirm_downgrade=body.confirm_downgrade)
