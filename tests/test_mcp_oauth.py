"""MCP OAuth (openspec 2026-11-08-mcp, 1.8): protocol, encrypted state, token scoping and refresh."""
import base64
import hashlib
from datetime import timedelta
from uuid import UUID, uuid4

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import select

from nexus_api.dependencies.platform import get_database_session
from nexus_api.main import app
from nexus_core.platform import Principal, TenantRole, utc_now
from nexus_mcp import oauth as proto
from nexus_mcp.client import McpError, fingerprint, is_unauthorized, replace_authorization, validate_config
from nexus_platform.errors import InvalidConfiguration, PlatformError
from nexus_platform.mcp import oauth as lifecycle
from nexus_platform.mcp import service as mcp
from nexus_platform.persistence.models import McpOAuthClientRecord, McpOAuthTokenRecord
from nexus_platform.tenants.service import add_member, create_tenant
from test_platform import database  # noqa: F401  (fixture)

PRINCIPAL = Principal(id="alice", issuer="test")
OTHER = Principal(id="bob", issuer="test")
AS_URL = "https://as.example"
TOKEN_URL = f"{AS_URL}/token"
CLIENT = proto.OAuthClient(client_id="client-1", client_secret="secret-1",
                           redirect_uri="https://nexus.example/api/v1/mcp-services/oauth/callback")
SERVER = proto.AuthorizationServer(
    issuer=AS_URL, authorization_endpoint=f"{AS_URL}/authorize", token_endpoint=TOKEN_URL,
    registration_endpoint=f"{AS_URL}/register",
    metadata_url=f"{AS_URL}/.well-known/oauth-authorization-server")


@pytest.fixture(autouse=True)
def _cipher(monkeypatch):
    """A per-test Fernet key, so tests never depend on the developer's configs/nexus.toml."""
    import nexus_platform.models.provider_settings as settings
    key = Fernet.generate_key()
    monkeypatch.setattr(settings, "cipher", lambda: Fernet(key))


def _oauth_service(factory, *, dynamic: bool = False):
    with factory() as db:
        tenant = create_tenant(db, PRINCIPAL, "OAuth")
    oauth_block = {"scopes": ["read"], "auth_server_metadata_url": f"{AS_URL}/.well-known/oauth-authorization-server"}
    if not dynamic:
        oauth_block.update(client_id="client-1", client_secret="secret-1")
    with factory() as db:
        created = mcp.create_service(
            db, PRINCIPAL, tenant.id, name="remote", description="",
            transport="streamable_http",
            config={"url": "https://mcp.example/api", "auth_type": "oauth", "oauth": oauth_block})
    return tenant, UUID(created["id"])


@pytest.fixture
def patched(monkeypatch):
    """No network: fixed discovery, fixed dynamic registration, recording token calls."""
    calls = {"exchange": 0, "refresh": 0, "register": 0}
    outcome = {"exchange": None, "refresh": None}

    monkeypatch.setattr(lifecycle, "_discover", lambda service, settings: SERVER)

    async def fake_register(server, redirect_uri, scopes=(), **_kw):
        calls["register"] += 1
        return proto.OAuthClient(client_id="dyn-client", client_secret="dyn-secret",
                                 redirect_uri=redirect_uri, metadata_url=server.metadata_url,
                                 token_endpoint_auth_method="client_secret_post")

    async def fake_exchange(server, client, *, code, code_verifier, redirect_uri, resource=None, **_kw):
        calls["exchange"] += 1
        calls["exchange_args"] = {"code": code, "verifier": code_verifier,
                                  "redirect_uri": redirect_uri, "resource": resource,
                                  "client_id": client.client_id}
        if isinstance(outcome["exchange"], Exception):
            raise outcome["exchange"]
        return outcome["exchange"] or proto.TokenSet(
            access_token="access-1", refresh_token="refresh-1",
            expires_at=utc_now() + timedelta(hours=1), scope="read")

    async def fake_refresh(server, client, refresh_token, *, resource=None, **_kw):
        calls["refresh"] += 1
        calls["refresh_arg"] = refresh_token
        if isinstance(outcome["refresh"], Exception):
            raise outcome["refresh"]
        return outcome["refresh"] or proto.TokenSet(
            access_token="access-2", refresh_token="refresh-2",
            expires_at=utc_now() + timedelta(hours=1), scope="read")

    monkeypatch.setattr(proto, "register_client", fake_register)
    monkeypatch.setattr(proto, "exchange_code", fake_exchange)
    monkeypatch.setattr(proto, "refresh_token", fake_refresh)
    return calls, outcome


# --------------------------------------------------------------------------- protocol

def test_pkce_challenge_is_s256_of_verifier():
    verifier, challenge = proto.generate_pkce()
    assert 43 <= len(verifier) <= 128
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    assert challenge == base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def test_authorization_url_carries_pkce_state_scope_and_resource():
    url = proto.authorization_url(SERVER, "client-1", "https://nexus.example/cb", state="state-1",
                                  code_challenge="challenge-1", scopes=("read", "write"),
                                  resource="https://mcp.example/api")
    params = dict(httpx.URL(url).params)
    assert url.startswith(f"{AS_URL}/authorize?")
    assert params["response_type"] == "code"
    assert params["client_id"] == "client-1"
    assert params["code_challenge_method"] == "S256"
    assert params["scope"] == "read write"
    assert params["resource"] == "https://mcp.example/api"


def test_oauth_endpoints_must_be_secure_outside_loopback():
    with pytest.raises(proto.OAuthConfigurationError):
        proto.authorization_url(proto.AuthorizationServer("http://as.example", "http://as.example/a",
                                                          "http://as.example/t"),
                                "client-1", "https://nexus.example/cb", state="s", code_challenge="c")
    loopback = proto.AuthorizationServer("http://127.0.0.1:9000", "http://127.0.0.1:9000/a",
                                         "http://127.0.0.1:9000/t")
    assert "code_challenge=" in proto.authorization_url(loopback, "client-1", "https://n.example/cb",
                                                        state="s", code_challenge="c")


def test_discovery_uses_protected_resource_metadata_then_authorization_server():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/.well-known/oauth-protected-resource/api":
            return httpx.Response(200, json={"authorization_servers": [AS_URL]})
        if request.url.path == "/.well-known/oauth-authorization-server":
            return httpx.Response(200, json={
                "issuer": AS_URL, "authorization_endpoint": f"{AS_URL}/authorize",
                "token_endpoint": TOKEN_URL, "registration_endpoint": f"{AS_URL}/register",
                "scopes_supported": ["read", 3]})
        return httpx.Response(404)

    async def scenario():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            return await proto.discover("https://mcp.example/api", client=client)
        finally:
            await client.aclose()

    import asyncio
    discovered = asyncio.run(scenario())
    assert discovered.authorization_endpoint == f"{AS_URL}/authorize"
    assert discovered.registration_endpoint == f"{AS_URL}/register"
    assert discovered.scopes_supported == ("read",)
    assert discovered.metadata_url == f"{AS_URL}/.well-known/oauth-authorization-server"


def test_metadata_for_another_origin_is_rejected():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "issuer": "https://evil.example", "authorization_endpoint": "https://evil.example/a",
            "token_endpoint": "https://evil.example/t"})

    async def scenario():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            return await proto.discover("https://mcp.example/api", client=client)
        finally:
            await client.aclose()

    import asyncio
    with pytest.raises(proto.OAuthConfigurationError):
        asyncio.run(scenario())


def _token_handler(response: dict, status: int = 200, seen: dict | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.update(dict(httpx.QueryParams(request.content.decode())))
        return httpx.Response(status, json=response)
    return handler


def _run(coro):
    import asyncio
    return asyncio.run(coro)


def test_exchange_code_sends_verifier_and_resource():
    seen: dict = {}
    async def scenario():
        client = httpx.AsyncClient(transport=httpx.MockTransport(
            _token_handler({"access_token": "at", "refresh_token": "rt", "expires_in": 3600}, seen=seen)))
        try:
            return await proto.exchange_code(SERVER, CLIENT, code="code-1", code_verifier="v-1",
                                             redirect_uri="https://n.example/cb",
                                             resource="https://mcp.example/api", client_http=client)
        finally:
            await client.aclose()

    tokens = _run(scenario())
    assert tokens.access_token == "at" and tokens.refresh_token == "rt"
    assert seen["grant_type"] == "authorization_code"
    assert seen["code_verifier"] == "v-1"
    assert seen["resource"] == "https://mcp.example/api"
    assert seen["client_secret"] == "secret-1"


def test_rejected_grant_requires_authorization_and_rejected_client_resets_it():
    async def scenario(body, status):
        client = httpx.AsyncClient(transport=httpx.MockTransport(_token_handler(body, status=status)))
        try:
            return await proto.refresh_token(SERVER, CLIENT, "rt", client_http=client)
        finally:
            await client.aclose()

    with pytest.raises(proto.OAuthReauthorizationRequired) as grant:
        _run(scenario({"error": "invalid_grant"}, 400))
    assert grant.value.reset_client is False
    with pytest.raises(proto.OAuthReauthorizationRequired) as client_rejected:
        _run(scenario({"error": "invalid_client"}, 401))
    assert client_rejected.value.reset_client is True
    with pytest.raises(proto.OAuthUnavailable):
        _run(scenario({"error": "server_error"}, 503))


def test_401_detection_follows_the_exception_chain():
    class Transport(Exception):
        status_code = 401

    try:
        try:
            raise McpError("Unauthorized")
        except McpError as inner:
            raise RuntimeError("wrapped") from inner
    except RuntimeError as exc:
        assert is_unauthorized(exc)
    assert is_unauthorized(Transport("boom"))
    assert not is_unauthorized(RuntimeError("connection reset"))


# --------------------------------------------------------------------------- config

def test_oauth_config_is_normalized_and_only_for_http_transports():
    config = validate_config({"transport": "streamable_http", "url": "https://mcp.example/api",
                              "auth_type": "oauth",
                              "oauth": {"scopes": ["read"], "client_secret": {"$credential_ref": "ref-1"}}})
    assert config["auth_type"] == "oauth"
    assert config["oauth"] == {"scopes": ["read"], "client_id": None,
                               "client_secret": {"$credential_ref": "ref-1"},
                               "auth_server_metadata_url": None}
    with pytest.raises(McpError):
        validate_config({"transport": "stdio", "command": "npx", "auth_type": "oauth"})
    with pytest.raises(McpError):
        validate_config({"transport": "streamable_http", "url": "https://x", "auth_type": "oauth",
                         "oauth": {"scopes": ["read", 3]}})
    with pytest.raises(McpError):
        validate_config({"transport": "streamable_http", "url": "https://x", "auth_type": "oauth",
                         "oauth": {"auth_server_metadata_url": "ftp://as.example/meta"}})


def test_fingerprint_ignores_secret_values_but_tracks_references_and_mode():
    base = {"transport": "streamable_http", "url": "https://mcp.example/api"}
    plain = validate_config({**base, "auth_type": "none"})
    secured = validate_config({**base, "auth_type": "oauth",
                               "oauth": {"client_secret": "secret-1"}})
    rotated = validate_config({**base, "auth_type": "oauth",
                               "oauth": {"client_secret": "secret-2"}})
    referenced = validate_config({**base, "auth_type": "oauth",
                                  "oauth": {"client_secret": {"$credential_ref": "ref-1"}}})
    assert fingerprint(plain) != fingerprint(secured)
    assert fingerprint(secured) == fingerprint(rotated)
    assert fingerprint(secured) != fingerprint(referenced)


def test_dynamic_token_replaces_static_authorization_header_once():
    headers = {"authorization": "Bearer stale", "X-Trace": "1"}
    merged = replace_authorization(headers, "Bearer fresh")
    assert merged == {"authorization": "Bearer fresh", "X-Trace": "1"}
    assert replace_authorization({}, "Bearer fresh") == {"Authorization": "Bearer fresh"}

    unresolved = validate_config({"transport": "streamable_http", "url": "https://x", "auth_type": "oauth",
                                  "oauth": {"client_secret": {"$credential_ref": "ref-1"}}})
    from nexus_mcp.client import assert_resolved
    with pytest.raises(McpError):
        assert_resolved(unresolved)


# --------------------------------------------------------------------------- platform lifecycle

def _begin(factory, tenant, service_id, *, frontend="/mcp"):
    with factory() as db:
        return lifecycle.begin_authorization(
            db, PRINCIPAL, tenant.id, service_id,
            redirect_uri="https://nexus.example/api/v1/mcp-services/oauth/callback",
            frontend_redirect=frontend)


def _complete(factory, state):
    with factory() as db:
        return lifecycle.complete_authorization(db, state, "code-1")


def _user_id(factory, principal=PRINCIPAL) -> UUID:
    """The platform user a principal maps to; tokens are keyed by this id, not the external one."""
    from nexus_platform.identity.service import resolve_user
    with factory() as db:
        return resolve_user(db, principal).id


def _access(factory, tenant_id, service_id, user_id, *, expect=None, **kw):
    """Resolve a token the way the worker does: inside the caller's transaction."""
    with factory() as db, db.begin():
        service = db.get(mcp.McpServiceRecord, service_id)
        if expect is None:
            return lifecycle.access_token(db, tenant_id, user_id, service, **kw)
        with pytest.raises(expect):
            lifecycle.access_token(db, tenant_id, user_id, service, **kw)


def _status(factory, principal, tenant_id, service_id):
    with factory() as db:
        return lifecycle.authorization_status(db, principal, tenant_id, service_id)


def test_authorization_round_trip_stores_an_encrypted_token(database, patched):
    tenant, service_id = _oauth_service(database)
    started = _begin(database, tenant, service_id)
    assert started["authorization_url"].startswith(f"{AS_URL}/authorize?")
    assert "code_challenge_method=S256" in started["authorization_url"]
    assert "resource=https%3A%2F%2Fmcp.example%2Fapi" in started["authorization_url"]

    result = _complete(database, started["state"])
    assert result["service_id"] == service_id and result["frontend_redirect"] == "/mcp"

    with database() as db:
        row = db.scalar(select(McpOAuthTokenRecord))
        assert row is not None
        assert "access-1" not in row.access_token and "refresh-1" not in row.refresh_token
        service = db.get(mcp.McpServiceRecord, service_id)
        assert lifecycle.access_token(db, tenant.id, row.principal_id, service) == "access-1"
    with database() as db:
        status = lifecycle.authorization_status(db, PRINCIPAL, tenant.id, service_id)
    assert status["authorized"] is True and status["state"] == "authorized"
    assert status["refresh_available"] is True


def test_tampered_or_expired_state_cannot_complete(database, patched, monkeypatch):
    tenant, service_id = _oauth_service(database)
    state = _begin(database, tenant, service_id)["state"]
    with pytest.raises(lifecycle.McpOAuthStateInvalid):
        _complete(database, state + "x")
    with pytest.raises(PlatformError):
        _complete(database, "garbage")

    monkeypatch.setattr(lifecycle, "STATE_TTL", timedelta(minutes=-1))
    expired = _begin(database, tenant, service_id)["state"]
    with pytest.raises(lifecycle.McpOAuthStateExpired) as exc:
        _complete(database, expired)
    assert exc.value.code == "mcp_oauth_state_expired"
    # The return path survives expiry so the workbench can explain the failure.
    assert lifecycle.frontend_redirect_for(expired) == "/mcp"
    assert lifecycle.frontend_redirect_for("garbage") == "/"


def test_frontend_redirect_must_stay_application_relative(database, patched):
    tenant, service_id = _oauth_service(database)
    with pytest.raises(InvalidConfiguration):
        _begin(database, tenant, service_id, frontend="https://evil.example/phish")
    with pytest.raises(InvalidConfiguration):
        _begin(database, tenant, service_id, frontend="//evil.example/phish")
    assert _begin(database, tenant, service_id, frontend="/agents?tab=mcp")["state"]


def test_expired_token_is_refreshed_lazily_and_rotates_the_grant(database, patched):
    calls, outcome = patched
    tenant, service_id = _oauth_service(database)
    user_id = _user_id(database)
    outcome["exchange"] = proto.TokenSet(access_token="old", refresh_token="refresh-1",
                                         expires_at=utc_now() - timedelta(seconds=1))
    _complete(database, _begin(database, tenant, service_id)["state"])

    assert _access(database, tenant.id, service_id, user_id) == "access-2"
    assert calls["refresh"] == 1 and calls["refresh_arg"] == "refresh-1"
    assert _status(database, PRINCIPAL, tenant.id, service_id)["state"] == "authorized"


def test_force_refresh_spends_exactly_one_refresh_and_keeps_prior_refresh_token(database, patched):
    calls, outcome = patched
    tenant, service_id = _oauth_service(database)
    user_id = _user_id(database)
    _complete(database, _begin(database, tenant, service_id)["state"])
    outcome["refresh"] = proto.TokenSet(access_token="access-3",
                                        expires_at=utc_now() + timedelta(hours=1))
    assert _access(database, tenant.id, service_id, user_id, force_refresh=True) == "access-3"
    assert calls["refresh"] == 1
    status = _status(database, PRINCIPAL, tenant.id, service_id)
    assert status["refresh_available"] is True  # RFC 6749 §6: the omitted refresh token is retained


def test_rejected_refresh_deletes_the_token_and_requires_reauthorization(database, patched):
    _, outcome = patched
    tenant, service_id = _oauth_service(database)
    user_id = _user_id(database)
    _complete(database, _begin(database, tenant, service_id)["state"])
    outcome["refresh"] = proto.OAuthReauthorizationRequired("revoked")
    _access(database, tenant.id, service_id, user_id, expect=lifecycle.McpOAuthRequired,
            force_refresh=True)
    # The removal is committed before the error unwinds the caller's transaction.
    with database() as db:
        assert db.scalar(select(McpOAuthTokenRecord)) is None
    assert _status(database, PRINCIPAL, tenant.id, service_id) == {
        "authorized": False, "state": "reauth_required", "refresh_available": False}


def test_rejected_client_registration_is_discarded(database, patched):
    _, outcome = patched
    tenant, service_id = _oauth_service(database, dynamic=True)
    user_id = _user_id(database)
    _complete(database, _begin(database, tenant, service_id)["state"])
    with database() as db:
        assert db.scalar(select(McpOAuthClientRecord)) is not None
    outcome["refresh"] = proto.OAuthReauthorizationRequired("client gone", reset_client=True)
    _access(database, tenant.id, service_id, user_id, expect=lifecycle.McpOAuthRequired,
            force_refresh=True)
    with database() as db:
        assert db.scalar(select(McpOAuthClientRecord)) is None
        assert db.scalar(select(McpOAuthTokenRecord)) is None


def test_tokens_are_scoped_to_the_authorizing_principal(database, patched):
    tenant, service_id = _oauth_service(database)
    with database() as db:
        add_member(db, PRINCIPAL, tenant.id, OTHER, TenantRole.CONTRIBUTOR)
    alice_id, bob_id = _user_id(database), _user_id(database, OTHER)
    _complete(database, _begin(database, tenant, service_id)["state"])

    assert _status(database, OTHER, tenant.id, service_id)["state"] == "reauth_required"
    # Another member cannot borrow alice's token: they must authorize their own.
    _access(database, tenant.id, service_id, bob_id, expect=lifecycle.McpOAuthRequired)
    assert _access(database, tenant.id, service_id, alice_id) == "access-1"
    with database() as db:
        lifecycle.revoke_authorization(db, OTHER, tenant.id, service_id)
    assert _status(database, PRINCIPAL, tenant.id, service_id)["authorized"] is True


# --------------------------------------------------------------------------- callback endpoint

@pytest.fixture
def callback_api(database):
    app.state.session_factory = database

    def override_db():
        with database() as db:
            yield db

    app.dependency_overrides[get_database_session] = override_db
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()
    app.state.session_factory = None


def test_callback_redirects_with_a_fragment_result(callback_api, database, monkeypatch):
    service_id = uuid4()

    def fake_complete(db, state, code):
        return {"tenant_id": UUID(int=1), "service_id": service_id,
                "principal_id": UUID(int=2), "frontend_redirect": "/agents/42"}

    monkeypatch.setattr(lifecycle, "complete_authorization", fake_complete)
    response = callback_api.get("/api/v1/mcp-services/oauth/callback",
                                params={"state": "s", "code": "c"}, follow_redirects=False)
    assert response.status_code == 303
    location = response.headers["location"]
    assert location.startswith("/agents/42#")
    assert "mcp_oauth_result=success" in location and f"mcp_oauth_service={service_id}" in location


def test_callback_reports_errors_without_reflecting_provider_text(callback_api, monkeypatch):
    response = callback_api.get("/api/v1/mcp-services/oauth/callback",
                                params={"error": "access_denied"},
                                follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/#mcp_oauth_result=error&mcp_oauth_error=access_denied"

    unsafe = callback_api.get("/api/v1/mcp-services/oauth/callback",
                              params={"error": "<script>alert(1)</script>"},
                              follow_redirects=False)
    assert "mcp_oauth_denied" in unsafe.headers["location"]

    def failed(db, state, code):
        raise lifecycle.McpOAuthStateExpired()

    monkeypatch.setattr(lifecycle, "complete_authorization", failed)
    expired = callback_api.get("/api/v1/mcp-services/oauth/callback",
                               params={"state": "s", "code": "c"}, follow_redirects=False)
    assert "mcp_oauth_error=mcp_oauth_state_expired" in expired.headers["location"]
