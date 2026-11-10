"""Mount the stateless MCP endpoint at ``/mcp/{endpoint_id}`` (openspec 2026-11-08-mcp, 2.5).

A single :class:`EndpointMCPServer` serves every endpoint. A bearer middleware runs ahead of the
global session Auth because an MCP client authenticates with its endpoint's long-lived token, not a
user session: it hashes the bearer token, resolves the live endpoint, checks it against the path's
endpoint id, and installs an :class:`~nexus_platform.mcp.stateless.EndpointContext` (tenant, owner,
KB scope, tool whitelist) on a contextvar before the streamable-HTTP handler runs.

Every failure to resolve — unknown token, revoked, disabled, or a token that does not belong to the
path's endpoint — returns the same ``401 unauthorized`` so the protocol never reveals whether a
resource exists.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator, Callable
from uuid import UUID

from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.types import ASGIApp, Receive, Scope, Send

from nexus_mcp.server import EndpointMCPServer
from nexus_platform.errors import Forbidden
from . import service, stateless

_UNAUTHORIZED_BODY = {"error": {"code": "unauthorized", "message": "unauthorized"}}
_UNAVAILABLE_BODY = {"error": {"code": "service_unavailable", "message": "Platform storage is unavailable"}}


def _bearer_token(scope: Scope) -> str:
    headers = dict(scope.get("headers") or [])
    authorization = headers.get(b"authorization", b"").decode("latin-1")
    scheme, _, value = authorization.partition(" ")
    if scheme.casefold() != "bearer" or not value.strip():
        return ""
    return value.strip()


class _EndpointAuthMiddleware:
    """Resolve the bearer token and scope the contextvar before the MCP handler; 401 on any failure."""

    def __init__(self, get_app: Callable[[], ASGIApp], resolve_factory: Callable[[], object]) -> None:
        self.get_app = get_app
        self.resolve_factory = resolve_factory

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.get_app()(scope, receive, send)
            return
        # The path relative to the mount prefix (``root_path``) — ``scope["path"]`` still carries it.
        path = scope.get("path", "")
        root_path = scope.get("root_path", "")
        if root_path and path.startswith(root_path):
            path = path[len(root_path):]
        try:
            endpoint_id = UUID(path.strip("/"))
        except (ValueError, AttributeError):
            # Not an endpoint path (a trailing slash, a static asset, ...): let the router 404 it.
            await self.get_app()(scope, receive, send)
            return
        try:
            factory = self.resolve_factory()
        except Exception:  # noqa: BLE001 - database configuration must not crash the endpoint
            response = JSONResponse(_UNAVAILABLE_BODY, status_code=503)
            await response(scope, receive, send)
            return
        token = _bearer_token(scope)
        endpoint = None
        if token:
            try:
                with factory() as db:
                    endpoint = service.resolve_endpoint_token(db, token)
            except Forbidden:
                endpoint = None
        if endpoint is None or endpoint.id != endpoint_id:
            response = JSONResponse(_UNAUTHORIZED_BODY, status_code=401,
                                    headers={"WWW-Authenticate": "Bearer"})
            await response(scope, receive, send)
            return
        endpoint_scope = stateless.EndpointScope(
            tenant_id=endpoint.tenant_id,
            owner_id=endpoint.created_by,
            kb_ids=tuple(UUID(value) for value in (endpoint.kb_ids or [])),
            allowlist=frozenset(endpoint.tool_allowlist or []),
        )
        stateless.set_current(stateless.EndpointContext(endpoint_scope, factory))
        try:
            await self.get_app()(scope, receive, send)
        finally:
            stateless.set_current(None)


def endpoint_app(resolve_factory: Callable[[], object]) -> Starlette:
    """The mounted app: a shared endpoint MCP server behind the bearer middleware.

    ``resolve_factory`` returns the platform session factory (lazily, sharing the API's engine). The
    SDK's session manager must run its task group even in stateless mode, and can only be ``run()``
    once per instance, so a fresh server + streamable-HTTP app is built on every lifespan entry and
    swapped into the middleware; the caller (the API's lifespan) must enter this app's lifespan too,
    since Starlette does not run mounted apps' lifespans.
    """
    current: dict[str, ASGIApp] = {}

    def _fresh_mcp_app() -> ASGIApp:
        server = EndpointMCPServer(stateless.list_tools, stateless.execute_tool)
        return server.streamable_http_app(streamable_http_path="/{endpoint_id}", stateless_http=True)

    wrapped = _EndpointAuthMiddleware(lambda: current["app"], resolve_factory)

    @asynccontextmanager
    async def lifespan(_app: Starlette) -> AsyncIterator[None]:
        mcp_app = _fresh_mcp_app()
        current["app"] = mcp_app
        try:
            async with mcp_app.router.lifespan_context(mcp_app):
                yield
        finally:
            current.pop("app", None)

    return Starlette(routes=[Route("/{path:path}", endpoint=wrapped)], lifespan=lifespan)
