"""MCP service management endpoints (openspec 2026-11-08-mcp, task 1.7).

CRUD, discovery and per-tool enablement are administrator capabilities (``tools:manage``); listing
is available to every active member. Connection config returns credential-reference markers, never
resolved secrets.
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlencode
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from nexus_core.platform import Principal
from nexus_platform.errors import PlatformError
from nexus_platform.mcp import oauth as mcp_oauth
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


class OAuthAuthorizeRequest(BaseModel):
    """The backend callback URL registered with the authorization server, plus the SPA path to return to."""

    redirect_uri: str = Field(min_length=1, max_length=1024)
    frontend_redirect: str | None = Field(default=None, max_length=2048)


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


# --------------------------------------------------------------------------- OAuth (task 1.8)

def _callback_target(state: str) -> str:
    """The SPA path to return to after the callback; ``"/"`` when the state cannot be trusted."""
    return mcp_oauth.frontend_redirect_for(state) if state else "/"


def _redirect_with_result(target: str, *, error: str = "", service_id: str = "") -> RedirectResponse:
    """Send the browser back to the SPA with the outcome in the fragment (never in server logs)."""
    params = {"mcp_oauth_result": "error" if error else "success"}
    if error:
        params["mcp_oauth_error"] = error
    if service_id:
        params["mcp_oauth_service"] = service_id
    return RedirectResponse(f"{target}#{urlencode(params)}", status_code=303)


@router.post("/tenants/{tenant_id}/mcp-services/{service_id}/oauth/authorize-url")
def mcp_oauth_authorize_url(tenant_id: UUID, service_id: UUID, body: OAuthAuthorizeRequest,
                            principal: Principal = Depends(get_principal),
                            db: Session = Depends(get_database_session)) -> dict[str, Any]:
    """Start the authorization-code + PKCE flow for the calling principal.

    `redirect_uri` is this API's public callback; `frontend_redirect` is the application-relative
    path the callback returns the browser to. Any active member authorizes their own token; a
    dynamically registered client is stored per (tenant, service) and reused.
    """
    return mcp_oauth.begin_authorization(db, principal, tenant_id, service_id,
                                         redirect_uri=body.redirect_uri,
                                         frontend_redirect=body.frontend_redirect)


@router.get("/tenants/{tenant_id}/mcp-services/{service_id}/oauth/status")
def mcp_oauth_status(tenant_id: UUID, service_id: UUID, principal: Principal = Depends(get_principal),
                     db: Session = Depends(get_database_session)) -> dict[str, Any]:
    """Whether the caller's token is usable, merely refreshable, or must be re-authorized."""
    return mcp_oauth.authorization_status(db, principal, tenant_id, service_id)


@router.delete("/tenants/{tenant_id}/mcp-services/{service_id}/oauth/token", status_code=204)
def mcp_oauth_revoke(tenant_id: UUID, service_id: UUID, principal: Principal = Depends(get_principal),
                     db: Session = Depends(get_database_session)) -> None:
    """Forget the caller's token; the next call asks for authorization again."""
    mcp_oauth.revoke_authorization(db, principal, tenant_id, service_id)


@router.get("/mcp-services/oauth/callback")
def mcp_oauth_callback(state: str = Query(default="", max_length=8192),
                       code: str = Query(default="", max_length=8192),
                       error: str = Query(default="", max_length=128),
                       db: Session = Depends(get_database_session)) -> RedirectResponse:
    """Public authorization-server callback: exchange `code` and return to the SPA.

    No session is required (the browser arrives from the authorization server); the encrypted,
    expiring ``state`` carries the principal and PKCE verifier and is the only thing authorizing
    the exchange. Failures still redirect so the workbench can explain them.
    """
    if error or not code or not state:
        # Never reflect arbitrary provider text: only a plain OAuth error code is passed through.
        reason = error if re.fullmatch(r"[a-z][a-z_]{0,63}", error) else "mcp_oauth_denied"
        return _redirect_with_result(_callback_target(state), error=reason)
    try:
        result = mcp_oauth.complete_authorization(db, state, code)
    except PlatformError as exc:
        return _redirect_with_result(_callback_target(state), error=exc.code)
    return _redirect_with_result(str(result["frontend_redirect"]),
                                 service_id=str(result["service_id"]))


# --------------------------------------------------------------------------- endpoints (task 2.6)

class McpEndpointCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    description: str = Field(default="", max_length=4000)
    tool_allowlist: list[str] = Field(default_factory=list, max_length=100)
    kb_ids: list[str] = Field(default_factory=list, max_length=100)


class McpEndpointUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    description: str | None = Field(default=None, max_length=4000)
    tool_allowlist: list[str] | None = Field(default=None, max_length=100)
    kb_ids: list[str] | None = Field(default=None, max_length=100)
    enabled: bool | None = None


@router.get("/tenants/{tenant_id}/mcp-endpoints")
def list_mcp_endpoints(tenant_id: UUID, principal: Principal = Depends(get_principal),
                       db: Session = Depends(get_database_session)) -> list[dict[str, Any]]:
    """Every MCP endpoint in this Tenant. Requires active membership."""
    return mcp.list_endpoints(db, principal, tenant_id)


@router.post("/tenants/{tenant_id}/mcp-endpoints", status_code=201)
def create_mcp_endpoint(tenant_id: UUID, body: McpEndpointCreate, principal: Principal = Depends(get_principal),
                        db: Session = Depends(get_database_session)) -> dict[str, Any]:
    """Create an endpoint and issue its long-lived token (shown once in this response). Administrators."""
    return mcp.create_endpoint(db, principal, tenant_id, name=body.name, description=body.description,
                               tool_allowlist=body.tool_allowlist, kb_ids=body.kb_ids)


@router.get("/tenants/{tenant_id}/mcp-endpoints/{endpoint_id}")
def get_mcp_endpoint(tenant_id: UUID, endpoint_id: UUID, principal: Principal = Depends(get_principal),
                     db: Session = Depends(get_database_session)) -> dict[str, Any]:
    return mcp.get_endpoint(db, principal, tenant_id, endpoint_id)


@router.patch("/tenants/{tenant_id}/mcp-endpoints/{endpoint_id}")
def update_mcp_endpoint(tenant_id: UUID, endpoint_id: UUID, body: McpEndpointUpdate,
                        principal: Principal = Depends(get_principal),
                        db: Session = Depends(get_database_session)) -> dict[str, Any]:
    """Update name, description, tool whitelist, KB scope or enabled. Administrators."""
    return mcp.update_endpoint(db, principal, tenant_id, endpoint_id, name=body.name,
                               description=body.description, tool_allowlist=body.tool_allowlist,
                               kb_ids=body.kb_ids, enabled=body.enabled)


@router.delete("/tenants/{tenant_id}/mcp-endpoints/{endpoint_id}", status_code=204)
def delete_mcp_endpoint(tenant_id: UUID, endpoint_id: UUID, principal: Principal = Depends(get_principal),
                        db: Session = Depends(get_database_session)) -> None:
    mcp.delete_endpoint(db, principal, tenant_id, endpoint_id)


@router.post("/tenants/{tenant_id}/mcp-endpoints/{endpoint_id}/rotate-token")
def rotate_mcp_endpoint_token(tenant_id: UUID, endpoint_id: UUID, principal: Principal = Depends(get_principal),
                              db: Session = Depends(get_database_session)) -> dict[str, Any]:
    """Issue a new token (shown once in this response); the old one stops working. Administrators."""
    return mcp.rotate_endpoint_token(db, principal, tenant_id, endpoint_id)


@router.post("/tenants/{tenant_id}/mcp-endpoints/{endpoint_id}/revoke-token")
def revoke_mcp_endpoint_token(tenant_id: UUID, endpoint_id: UUID, principal: Principal = Depends(get_principal),
                              db: Session = Depends(get_database_session)) -> dict[str, Any]:
    """Clear the token hash so no token authenticates until the next rotate. Administrators."""
    return mcp.revoke_endpoint_token(db, principal, tenant_id, endpoint_id)
