"""MCP integration tests (openspec 2026-11-08-mcp, 3.2).

Everything here speaks MCP to a live endpoint: the SDK's own ``MCPServer`` is served over stdio
(a real subprocess), streamable HTTP and SSE, and a fake authorization server plus a bearer-guarded
MCP resource exercise the OAuth authorization-code flow end to end. Only the platform's persistence
is shared with the unit tests; no transport, discovery or token call is mocked.
"""
from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import secrets
import sys
import threading
import time
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

import httpx
import pytest
import uvicorn
from cryptography.fernet import Fernet
from sqlalchemy import select
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse
from starlette.routing import Mount, Route

from nexus_core.platform import Principal, utc_now
from nexus_core.runtime import ToolDefinition, ToolResult
from nexus_mcp import client as mcp_client
from nexus_mcp._sdk import MCPServer, ToolAnnotations
from nexus_mcp.server import EndpointMCPServer, streamable_http_app
from nexus_platform.errors import Forbidden
from nexus_platform.identity.service import resolve_user
from nexus_platform.mcp import oauth as lifecycle
from nexus_platform.mcp import service as mcp
from nexus_platform.mcp import stateless
from nexus_platform.persistence.models import McpOAuthTokenRecord
from test_platform import database  # noqa: F401  (fixture)

PRINCIPAL = Principal(id="alice", issuer="test")

_STDIO_SERVER = '''
from mcp.server import MCPServer
from mcp.types import ToolAnnotations

server = MCPServer("integration-stdio")


@server.tool(annotations=ToolAnnotations(readOnlyHint=True))
def echo(text: str) -> str:
    """Echo the text back."""
    return "echo:" + text


server.run(transport="stdio")
'''


# --------------------------------------------------------------------------- live servers

@contextlib.contextmanager
def _serve(app):
    """Run an ASGI app on a free loopback port in a background thread; yield its base URL."""
    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning", lifespan="on",
                            timeout_graceful_shutdown=5)
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 30
    while not server.started:
        if not thread.is_alive() or time.monotonic() > deadline:
            raise RuntimeError("MCP test server did not start")
        time.sleep(0.02)
    port = server.servers[0].sockets[0].getsockname()[1]
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=30)
        assert not thread.is_alive(), "MCP test server did not shut down"


def _fake_mcp_server() -> MCPServer:
    server = MCPServer("integration-fake")

    @server.tool(annotations=ToolAnnotations(readOnlyHint=True))
    def echo(text: str) -> str:
        """Echo the text back."""
        return f"echo:{text}"

    return server


def _run(coro):
    return asyncio.run(coro)


# --------------------------------------------------------------------------- transports

def test_discover_and_call_over_http_sse_and_stdio(tmp_path):
    """The same fake service works through all three transports the client supports."""
    server = _fake_mcp_server()
    with _serve(server.streamable_http_app()) as base:
        config = {"transport": "streamable_http", "url": base + "/mcp"}
        specs = _run(mcp_client.discover(config, timeout=15))
        assert [spec.name for spec in specs] == ["echo"]
        assert specs[0].read_only_hint is True
        assert _run(mcp_client.call(config, "echo", {"text": "http"}, timeout=15)).data == "echo:http"

    with _serve(server.sse_app()) as base:
        config = {"transport": "sse", "url": base + "/sse", "sse_read_timeout": 5}
        assert [spec.name for spec in _run(mcp_client.discover(config, timeout=15))] == ["echo"]
        assert _run(mcp_client.call(config, "echo", {"text": "sse"}, timeout=15)).data == "echo:sse"

    script = tmp_path / "stdio_server.py"
    script.write_text(_STDIO_SERVER, encoding="utf-8")
    config = {"transport": "stdio", "command": sys.executable, "args": [str(script)], "env": {}}
    assert [spec.name for spec in _run(mcp_client.discover(config, timeout=15))] == ["echo"]
    assert _run(mcp_client.call(config, "echo", {"text": "stdio"}, timeout=15)).data == "echo:stdio"


def test_disabled_service_is_rechecked_before_each_call(database):
    """A service disabled after discovery refuses the next call instead of calling through."""
    tenant = _tenant(database)
    with _serve(_fake_mcp_server().streamable_http_app()) as base:
        created = _create_service(database, tenant, base + "/mcp")
        service_id = UUID(created["id"])
        with database() as db:
            assert mcp.discover_tools(db, PRINCIPAL, tenant.id, service_id)["tools"] == ["echo"]
        with database() as db:
            mcp.set_enabled_tools(db, PRINCIPAL, tenant.id, service_id, ["echo"])
        with database() as db:
            resolved, _schema, timeout = mcp.resolve_call(db, tenant.id, service_id, "echo")
        assert _run(mcp_client.call(resolved, "echo", {"text": "before"}, timeout=timeout)).data == "echo:before"

        with database() as db:
            mcp.update_service(db, PRINCIPAL, tenant.id, service_id, name=None, description=None,
                               transport=None, config=None, enabled=False)
        with database() as db:
            with pytest.raises(mcp.McpServiceDisabled):
                mcp.resolve_call(db, tenant.id, service_id, "echo")


# --------------------------------------------------------------------------- endpoint tokens + server

def test_endpoint_token_lifecycle_and_server_protocol(database):
    """An endpoint token authorizes the server's tools/list and tools/call until revoked."""
    tenant = _tenant(database)
    with database() as db:
        created = mcp.create_endpoint(db, PRINCIPAL, tenant.id, name="readonly", description="",
                                      tool_allowlist=["list_documents", "search_memory"], kb_ids=[])
        endpoint_id = UUID(created["id"])
        token = created["token"]

    with database() as db:
        assert mcp.resolve_endpoint_token(db, token).id == endpoint_id

    definitions = [stateless.TOOL_DEFINITIONS["list_documents"], stateless.TOOL_DEFINITIONS["search_memory"]]

    def _authorize() -> None:
        with database() as db:
            mcp.resolve_endpoint_token(db, token)

    async def list_definitions() -> list[ToolDefinition]:
        _authorize()
        return definitions

    async def execute(name: str, arguments: dict) -> ToolResult:
        _authorize()
        return ToolResult("ok")

    app = streamable_http_app(EndpointMCPServer(list_definitions, execute))
    with _serve(app) as nexus_base:
        nexus_config = {"transport": "streamable_http", "url": nexus_base + "/mcp"}
        specs = _run(mcp_client.discover(nexus_config, timeout=15))
        assert [spec.name for spec in specs] == ["list_documents", "search_memory"]
        assert specs[0].read_only_hint is True
        assert _run(mcp_client.call(nexus_config, "list_documents", {}, timeout=15)).data == "ok"

        with database() as db:
            mcp.revoke_endpoint_token(db, PRINCIPAL, tenant.id, endpoint_id)
            with pytest.raises(Forbidden):
                mcp.resolve_endpoint_token(db, token)
        with pytest.raises(mcp_client.McpError):
            _run(mcp_client.discover(nexus_config, timeout=15))
        with pytest.raises(mcp_client.McpError):
            _run(mcp_client.call(nexus_config, "list_documents", {}, timeout=15))


def test_endpoint_mount_serves_read_only_tools_with_bearer_token(database):
    """The mounted /mcp/{endpoint_id} authenticates the bearer token and dispatches whitelisted tools."""
    tenant = _tenant(database)
    with database() as db:
        created = mcp.create_endpoint(db, PRINCIPAL, tenant.id, name="readonly", description="",
                                      tool_allowlist=["list_documents"], kb_ids=[])
    endpoint_id = created["id"]
    token = created["token"]

    from nexus_platform.mcp.http import endpoint_app
    mcp_endpoint_app = endpoint_app(lambda: database)

    @contextlib.asynccontextmanager
    async def lifespan(_app):
        async with mcp_endpoint_app.router.lifespan_context(mcp_endpoint_app):
            yield

    outer = Starlette(routes=[Mount("/mcp", mcp_endpoint_app)], lifespan=lifespan)

    with _serve(outer) as base:
        good = {"transport": "streamable_http", "url": f"{base}/mcp/{endpoint_id}",
                "headers": {"Authorization": f"Bearer {token}"}}
        specs = _run(mcp_client.discover(good, timeout=15))
        assert [spec.name for spec in specs] == ["list_documents"]
        # the real stateless dispatch runs (empty KB scope, not the protocol's placeholder)
        result = _run(mcp_client.call(good, "list_documents", {}, timeout=15))
        assert "No readable knowledge base" in result.data

        # a wrong token is a uniform 401; it never reveals whether the endpoint exists
        bad = {"transport": "streamable_http", "url": f"{base}/mcp/{endpoint_id}",
               "headers": {"Authorization": "Bearer wrong"}}
        with pytest.raises(mcp_client.McpUnauthorized):
            _run(mcp_client.discover(bad, timeout=15))


# --------------------------------------------------------------------------- OAuth end to end

class _BearerGuard:
    """ASGI wrapper: only a token from the fake server's live set reaches the MCP app."""

    def __init__(self, owner: "_FakeOAuth"):
        self._owner = owner

    async def __call__(self, scope, receive, send):
        headers = dict(scope.get("headers") or [])
        authorization = headers.get(b"authorization", b"").decode("latin-1")
        token = authorization[7:] if authorization.lower().startswith("bearer ") else ""
        if token not in self._owner.access_tokens:
            host = headers.get(b"host", b"127.0.0.1").decode("latin-1")
            response = JSONResponse(
                {"error": "invalid_token"}, status_code=401,
                headers={"WWW-Authenticate":
                         f'Bearer resource_metadata="http://{host}/.well-known/oauth-protected-resource/mcp"'})
            return await response(scope, receive, send)
        return await self._owner.mcp_app(scope, receive, send)


class _FakeOAuth:
    """One origin serving RFC 9728 / RFC 8414 metadata, RFC 7591 registration, the authorize and
    token endpoints, and a bearer-guarded MCP endpoint (the resource server)."""

    def __init__(self) -> None:
        self.registrations = 0
        self.registration_payloads: list[dict] = []
        self.clients: dict[str, str] = {}
        self.codes: dict[str, dict] = {}
        self.access_tokens: set[str] = set()
        self.refresh_tokens: set[str] = set()
        self.authorization_requests: list[dict] = []
        self.token_grants: list[str] = []
        self.issued = 0
        self.last_access_token = ""
        self.mcp_app = _fake_mcp_server().streamable_http_app()

    def app(self) -> Starlette:
        inner_lifespan = self.mcp_app.router.lifespan_context

        @contextlib.asynccontextmanager
        async def lifespan(_app):
            # The MCP session manager runs in the mounted app's lifespan; the outer Starlette app
            # would otherwise start it never, and every streamable-HTTP request would fail.
            async with inner_lifespan(self.mcp_app):
                yield

        return Starlette(routes=[
            Route("/.well-known/oauth-protected-resource/mcp", self._resource_metadata),
            Route("/.well-known/oauth-protected-resource", self._resource_metadata),
            Route("/.well-known/oauth-authorization-server", self._as_metadata),
            Route("/register", self._register, methods=["POST"]),
            Route("/authorize", self._authorize),
            Route("/token", self._token, methods=["POST"]),
            Route("/mcp", endpoint=_BearerGuard(self)),
        ], lifespan=lifespan)

    def revoke_access_tokens(self) -> None:
        self.access_tokens.clear()

    def revoke_refresh_tokens(self) -> None:
        self.refresh_tokens.clear()

    async def _resource_metadata(self, request: Request) -> JSONResponse:
        base = _origin(request)
        return JSONResponse({"resource": base + "/mcp", "authorization_servers": [base],
                             "scopes_supported": ["read"]})

    async def _as_metadata(self, request: Request) -> JSONResponse:
        base = _origin(request)
        return JSONResponse({"issuer": base, "authorization_endpoint": base + "/authorize",
                             "token_endpoint": base + "/token",
                             "registration_endpoint": base + "/register",
                             "scopes_supported": ["read"]})

    async def _register(self, request: Request) -> JSONResponse:
        body = await request.json()
        self.registrations += 1
        self.registration_payloads.append(body)
        client_id = f"dyn-client-{self.registrations}"
        secret = f"dyn-secret-{self.registrations}"
        self.clients[client_id] = secret
        return JSONResponse({"client_id": client_id, "client_secret": secret,
                             "token_endpoint_auth_method": "client_secret_post",
                             "redirect_uris": body.get("redirect_uris", [])}, status_code=201)

    async def _authorize(self, request: Request) -> RedirectResponse:
        params = dict(request.query_params)
        self.authorization_requests.append(params)
        assert params["response_type"] == "code"
        assert params["code_challenge_method"] == "S256"
        code = secrets.token_urlsafe(16)
        self.codes[code] = {"challenge": params["code_challenge"], "client_id": params["client_id"],
                            "redirect_uri": params["redirect_uri"], "resource": params.get("resource")}
        return RedirectResponse(
            f"{params['redirect_uri']}?code={code}&state={params['state']}", status_code=302)

    async def _token(self, request: Request) -> JSONResponse:
        form = await request.form()
        client_id = str(form.get("client_id") or "")
        if self.clients.get(client_id) != form.get("client_secret"):
            return JSONResponse({"error": "invalid_client"}, status_code=401)
        grant = str(form.get("grant_type") or "")
        self.token_grants.append(grant)
        if grant == "authorization_code":
            record = self.codes.pop(str(form.get("code") or ""), None)
            if record is None or record["client_id"] != client_id \
                    or record["redirect_uri"] != form.get("redirect_uri") \
                    or record["challenge"] != _challenge(str(form.get("code_verifier") or "")):
                return JSONResponse({"error": "invalid_grant"}, status_code=400)
            return JSONResponse(self._issue())
        if grant == "refresh_token":
            token = str(form.get("refresh_token") or "")
            if token not in self.refresh_tokens:
                return JSONResponse({"error": "invalid_grant"}, status_code=400)
            self.refresh_tokens.discard(token)  # rotation: the old grant dies with the refresh
            return JSONResponse(self._issue())
        return JSONResponse({"error": "unsupported_grant_type"}, status_code=400)

    def _issue(self) -> dict:
        self.issued += 1
        access = f"at-{self.issued}"
        refresh = f"rt-{self.issued}"
        self.access_tokens = {access}
        self.refresh_tokens.add(refresh)
        self.last_access_token = access
        return {"access_token": access, "token_type": "Bearer", "expires_in": 3600,
                "refresh_token": refresh, "scope": "read"}


def _origin(request: Request) -> str:
    return str(request.base_url).rstrip("/")


def _challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


@pytest.fixture(autouse=True)
def _cipher(monkeypatch):
    """A per-test Fernet key, so tests never depend on the developer's configs/nexus.toml."""
    import nexus_platform.models.provider_settings as settings
    key = Fernet.generate_key()
    monkeypatch.setattr(settings, "cipher", lambda: Fernet(key))


def _tenant(factory):
    from nexus_platform.tenants.service import create_tenant
    with factory() as db:
        return create_tenant(db, PRINCIPAL, "MCP integration")


def _create_service(factory, tenant, url: str, **config):
    with factory() as db:
        return mcp.create_service(db, PRINCIPAL, tenant.id, name="remote", description="",
                                  transport="streamable_http", config={"url": url, **config})


def _expire_stored_token(factory, tenant_id, service_id) -> None:
    with factory() as db:
        row = db.scalar(select(McpOAuthTokenRecord).where(
            McpOAuthTokenRecord.tenant_id == tenant_id, McpOAuthTokenRecord.service_id == service_id))
        assert row is not None
        row.expires_at = utc_now() - timedelta(seconds=1)
        db.commit()


def _started_authorization(factory, tenant, service_id, redirect_uri):
    """Begin the flow and play the browser's part: the authorization endpoint redirects with a code."""
    with factory() as db:
        started = lifecycle.begin_authorization(
            db, PRINCIPAL, tenant.id, service_id, redirect_uri=redirect_uri,
            frontend_redirect="/tools/mcp")
    response = httpx.get(started["authorization_url"], follow_redirects=False)
    assert response.status_code == 302
    location = urlsplit(response.headers["location"])
    query = parse_qs(location.query)
    return started, location, query


def test_oauth_authorization_code_flow_end_to_end(database):
    """Register → authorize → exchange → discover/call → refresh → rejected grant."""
    tenant = _tenant(database)
    fake = _FakeOAuth()
    with _serve(fake.app()) as base:
        created = _create_service(database, tenant, base + "/mcp", auth_type="oauth",
                                  oauth={"scopes": ["read"]})
        service_id = UUID(created["id"])
        with database() as db:
            principal_id = resolve_user(db, PRINCIPAL).id

        with database() as db:
            with pytest.raises(lifecycle.McpOAuthRequired):
                mcp.discover_tools(db, PRINCIPAL, tenant.id, service_id)
        assert fake.registrations == 0

        redirect_uri = base + "/callback"
        started, location, query = _started_authorization(database, tenant, service_id, redirect_uri)
        assert fake.registrations == 1
        assert fake.registration_payloads[0]["redirect_uris"] == [redirect_uri]
        assert location.path == "/callback"
        assert query["state"][0] == started["state"]
        assert fake.authorization_requests[-1]["resource"] == base + "/mcp"
        code = query["code"][0]

        with database() as db:
            completed = lifecycle.complete_authorization(db, started["state"], code)
        assert completed["frontend_redirect"] == "/tools/mcp"
        assert fake.token_grants == ["authorization_code"]
        with database() as db:
            assert lifecycle.authorization_status(db, PRINCIPAL, tenant.id, service_id)["state"] == "authorized"

        with database() as db:
            assert mcp.discover_tools(db, PRINCIPAL, tenant.id, service_id)["tools"] == ["echo"]
        with database() as db:
            mcp.set_enabled_tools(db, PRINCIPAL, tenant.id, service_id, ["echo"])
        with database() as db:
            resolved, _schema, timeout = mcp.resolve_call(db, tenant.id, service_id, "echo", principal_id=principal_id)
        assert resolved["headers"]["Authorization"] == f"Bearer {fake.last_access_token}"
        assert _run(mcp_client.call(resolved, "echo", {"text": "oauth"}, timeout=timeout)).data == "echo:oauth"

        # Lazily refresh a token that is inside the 30 s skew.
        _expire_stored_token(database, tenant.id, service_id)
        with database() as db:
            resolved, _schema, timeout = mcp.resolve_call(db, tenant.id, service_id, "echo", principal_id=principal_id)
        assert fake.token_grants == ["authorization_code", "refresh_token"]
        assert resolved["headers"]["Authorization"] == f"Bearer {fake.last_access_token}"
        assert _run(mcp_client.call(resolved, "echo", {"text": "refreshed"}, timeout=timeout)).data == "echo:refreshed"

        # The resource server revoked the token: exactly one forced refresh and one retry.
        fake.revoke_access_tokens()
        with database() as db:
            assert mcp.discover_tools(db, PRINCIPAL, tenant.id, service_id)["tools"] == ["echo"]
        assert fake.token_grants[-1] == "refresh_token"

        # A 401 whose forced refresh the authorization server rejects asks for re-authorization
        # instead of degrading into a generic connection failure; the dead token is deleted.
        fake.revoke_access_tokens()
        fake.revoke_refresh_tokens()
        with database() as db:
            with pytest.raises(lifecycle.McpOAuthRequired):
                mcp.discover_tools(db, PRINCIPAL, tenant.id, service_id)
        with database() as db:
            with pytest.raises(lifecycle.McpOAuthRequired):
                mcp.resolve_call(db, tenant.id, service_id, "echo", principal_id=principal_id)
        with database() as db:
            assert lifecycle.authorization_status(
                db, PRINCIPAL, tenant.id, service_id)["state"] == "reauth_required"
