"""OAuth 2.1 authorization-code client for external MCP servers (openspec 2026-11-08-mcp, 1.8).

Protocol only: protected-resource and authorization-server discovery (RFC 9728 / RFC 8414),
dynamic client registration (RFC 7591), PKCE authorization URLs, code exchange and refresh.
Token storage, per-principal scope and the single 401 retry live in the platform
(``nexus_platform.mcp.oauth``), which owns the database and the deployment encryption key.

The module is deliberately independent of the MCP SDK: these requests are plain OAuth 2.1
HTTP calls, and keeping them here makes them testable with an injected ``httpx.AsyncClient``.
Nothing here logs or embeds an access/refresh token, client secret or raw token body.
"""
from __future__ import annotations

import base64
import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode, urlsplit

import httpx

from .client.errors import McpError

#: Discovery and token requests are small; a hung or hostile endpoint must not exhaust memory.
MAX_RESPONSE_BYTES = 256 * 1024
DEFAULT_TIMEOUT = 15.0
#: Refuse anything that is not HTTPS, except loopback development servers.
_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}


class OAuthError(McpError):
    """Base for OAuth failures; messages never carry tokens or secrets."""

    code = "mcp_oauth_failed"


class OAuthConfigurationError(OAuthError):
    """The service's OAuth settings or the discovered metadata are unusable."""

    code = "mcp_oauth_configuration_invalid"


class OAuthUnavailable(OAuthError):
    """A transient discovery/token-endpoint failure; retrying later may succeed."""

    code = "mcp_oauth_unavailable"


class OAuthReauthorizationRequired(OAuthError):
    """Only a new interactive authorization fixes the connection (invalid grant/client)."""

    code = "mcp_oauth_reauth_required"

    def __init__(self, message: str, *, reset_client: bool = False):
        super().__init__(message, code="mcp_oauth_reauth_required")
        self.reset_client = reset_client


@dataclass(frozen=True)
class AuthorizationServer:
    """The authorization-server metadata this client relies on."""

    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    registration_endpoint: str | None = None
    scopes_supported: tuple[str, ...] = ()
    #: URL the metadata document was actually read from (used to validate the issuer).
    metadata_url: str = ""


@dataclass(frozen=True)
class OAuthClient:
    """A dynamically registered (or pre-registered) OAuth client."""

    client_id: str
    client_secret: str | None = None
    redirect_uri: str = ""
    metadata_url: str = ""
    token_endpoint_auth_method: str = "client_secret_post"


@dataclass(frozen=True)
class TokenSet:
    """A token response. `expires_at` is None when the server omitted `expires_in`."""

    access_token: str
    token_type: str = "Bearer"
    refresh_token: str | None = None
    expires_at: datetime | None = None
    scope: str = ""


def generate_pkce() -> tuple[str, str]:
    """Return ``(code_verifier, code_challenge)`` using the S256 method (RFC 7636)."""
    verifier = secrets.token_urlsafe(64)[:128]
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def authorization_url(server: AuthorizationServer, client_id: str, redirect_uri: str, *,
                      state: str, code_challenge: str, scopes: list[str] | tuple[str, ...] = (),
                      resource: str | None = None) -> str:
    """Build the browser URL for the authorization-code + PKCE flow."""
    _require_secure(server.authorization_endpoint)
    params: dict[str, str] = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    if scopes:
        params["scope"] = " ".join(scopes)
    if resource:
        params["resource"] = resource
    separator = "&" if urlsplit(server.authorization_endpoint).query else "?"
    return f"{server.authorization_endpoint}{separator}{urlencode(params)}"


async def discover(resource_url: str, *, metadata_url: str | None = None,
                   timeout: float = DEFAULT_TIMEOUT,
                   client: httpx.AsyncClient | None = None) -> AuthorizationServer:
    """Discover the authorization server for an MCP resource URL.

    With `metadata_url` the document is used directly (an operator-pinned RFC 8414 URL).
    Otherwise RFC 9728 protected-resource metadata names the authorization server, with the
    resource origin as the legacy fallback. The issuer must share that server's origin.
    """
    _require_secure(resource_url)
    provided = client is not None
    http = client or httpx.AsyncClient(timeout=timeout, follow_redirects=False)
    try:
        if metadata_url:
            _require_secure(metadata_url)
            document = await _get_json(http, metadata_url)
            if document is None:
                raise OAuthConfigurationError("Authorization-server metadata is unavailable")
            return _parse_metadata(document, metadata_url)

        authorization_server = resource_url
        for candidate in _well_known_urls(resource_url, "oauth-protected-resource"):
            document = await _get_json(http, candidate)
            if document is None:
                continue
            servers = document.get("authorization_servers")
            if isinstance(servers, list) and servers and isinstance(servers[0], str):
                authorization_server = servers[0]
                break

        _require_secure(authorization_server)
        for candidate in _well_known_urls(authorization_server, "oauth-authorization-server"):
            document = await _get_json(http, candidate)
            if document is not None:
                return _parse_metadata(document, candidate)
        for candidate in _openid_configuration_urls(authorization_server):
            document = await _get_json(http, candidate)
            if document is not None:
                return _parse_metadata(document, candidate)
        raise OAuthConfigurationError("Authorization-server metadata was not found")
    finally:
        if not provided:
            await http.aclose()


async def register_client(server: AuthorizationServer, redirect_uri: str, *,
                          client_name: str = "Hyoga Nexus", scopes: list[str] | tuple[str, ...] = (),
                          timeout: float = DEFAULT_TIMEOUT,
                          client: httpx.AsyncClient | None = None) -> OAuthClient:
    """Register this client dynamically (RFC 7591). Fails when the server offers no endpoint."""
    if not server.registration_endpoint:
        raise OAuthConfigurationError(
            "This authorization server does not support automatic client registration; "
            "configure a pre-registered client_id and client_secret instead")
    _require_secure(server.registration_endpoint)
    provided = client is not None
    http = client or httpx.AsyncClient(timeout=timeout, follow_redirects=False)
    payload: dict[str, object] = {
        "client_name": client_name,
        "redirect_uris": [redirect_uri],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "client_secret_post",
    }
    if scopes:
        payload["scope"] = " ".join(scopes)
    try:
        response = await http.post(server.registration_endpoint, json=payload,
                                   headers={"Accept": "application/json"}, follow_redirects=False)
        if response.status_code not in (200, 201):
            raise OAuthConfigurationError(
                f"Dynamic client registration failed ({response.status_code})")
        body = _json_body(response)
        client_id = body.get("client_id")
        if not isinstance(client_id, str) or not client_id:
            raise OAuthConfigurationError("Dynamic client registration returned no client_id")
        client_secret = body.get("client_secret")
        auth_method = body.get("token_endpoint_auth_method")
        return OAuthClient(
            client_id=client_id,
            client_secret=client_secret if isinstance(client_secret, str) and client_secret else None,
            redirect_uri=redirect_uri,
            metadata_url=server.metadata_url,
            token_endpoint_auth_method=(auth_method if isinstance(auth_method, str) else
                                        ("client_secret_post" if client_secret else "none")),
        )
    finally:
        if not provided:
            await http.aclose()


async def exchange_code(server: AuthorizationServer, client: OAuthClient, *, code: str,
                        code_verifier: str, redirect_uri: str, resource: str | None = None,
                        timeout: float = DEFAULT_TIMEOUT,
                        client_http: httpx.AsyncClient | None = None) -> TokenSet:
    """Exchange one authorization code (with its PKCE verifier) for tokens."""
    return await _token_request(server, client, {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "code_verifier": code_verifier,
    }, resource=resource, timeout=timeout, http_client=client_http)


async def refresh_token(server: AuthorizationServer, client: OAuthClient, refresh_token: str, *,
                        resource: str | None = None, timeout: float = DEFAULT_TIMEOUT,
                        client_http: httpx.AsyncClient | None = None) -> TokenSet:
    """Refresh an access token. A rejected grant raises `OAuthReauthorizationRequired`."""
    return await _token_request(server, client, {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }, resource=resource, timeout=timeout, http_client=client_http)


# --------------------------------------------------------------------------- internals

def _require_secure(url: str) -> None:
    parsed = urlsplit(url)
    if parsed.scheme not in ("http", "https"):
        raise OAuthConfigurationError("OAuth endpoints must be http or https")
    if parsed.scheme == "https":
        return
    host = (parsed.hostname or "").casefold()
    if host in _LOOPBACK_HOSTS:
        return
    raise OAuthConfigurationError("OAuth endpoints must use HTTPS outside loopback development")


def _well_known_urls(base: str, name: str) -> list[str]:
    """RFC 8414 / RFC 9728 candidates: path-scoped first, then the origin root."""
    parsed = urlsplit(base)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    path = parsed.path.rstrip("/")
    urls: list[str] = []
    if path:
        urls.append(f"{origin}/.well-known/{name}{path}")
    urls.append(f"{origin}/.well-known/{name}")
    return urls


def _openid_configuration_urls(base: str) -> list[str]:
    parsed = urlsplit(base)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    path = parsed.path.rstrip("/")
    urls = [f"{origin}/.well-known/openid-configuration{path}" if path else
            f"{origin}/.well-known/openid-configuration"]
    if path:
        urls.append(f"{origin}/.well-known/openid-configuration")
    return urls


async def _get_json(client: httpx.AsyncClient, url: str) -> dict | None:
    response = await client.get(url, headers={"Accept": "application/json"},
                                follow_redirects=False)
    if response.status_code != 200:
        return None
    return _json_body(response)


def _json_body(response: httpx.Response) -> dict:
    if len(response.content) > MAX_RESPONSE_BYTES:
        raise OAuthError("OAuth endpoint response is too large")
    try:
        body = response.json()
    except ValueError:
        raise OAuthError("OAuth endpoint returned invalid JSON") from None
    if not isinstance(body, dict):
        raise OAuthError("OAuth endpoint returned a non-object JSON body")
    return body


def _parse_metadata(document: dict, metadata_url: str) -> AuthorizationServer:
    issuer = document.get("issuer")
    authorization_endpoint = document.get("authorization_endpoint")
    token_endpoint = document.get("token_endpoint")
    if not all(isinstance(value, str) and value for value in
               (issuer, authorization_endpoint, token_endpoint)):
        raise OAuthConfigurationError("Authorization-server metadata is missing required endpoints")
    # The issuer must belong to the server the document was read from; a document for another
    # origin would let whoever serves it redirect our tokens to their own endpoint.
    if _origin(issuer) != _origin(metadata_url):
        raise OAuthConfigurationError("Authorization-server metadata issuer does not match its origin")
    _require_secure(authorization_endpoint)
    _require_secure(token_endpoint)
    registration_endpoint = document.get("registration_endpoint")
    if registration_endpoint is not None:
        if not isinstance(registration_endpoint, str) or not registration_endpoint:
            raise OAuthConfigurationError("registration_endpoint is invalid")
        _require_secure(registration_endpoint)
    scopes = document.get("scopes_supported")
    return AuthorizationServer(
        issuer=issuer,
        authorization_endpoint=authorization_endpoint,
        token_endpoint=token_endpoint,
        registration_endpoint=registration_endpoint,
        scopes_supported=tuple(item for item in scopes if isinstance(item, str))
        if isinstance(scopes, list) else (),
        metadata_url=metadata_url,
    )


def _origin(url: str) -> tuple[str, str, int | None]:
    parsed = urlsplit(url)
    port = parsed.port or (443 if parsed.scheme == "https" else 80 if parsed.scheme == "http" else None)
    return parsed.scheme.casefold(), (parsed.hostname or "").casefold(), port


async def _token_request(server: AuthorizationServer, client: OAuthClient, data: dict[str, str], *,
                         resource: str | None, timeout: float,
                         http_client: httpx.AsyncClient | None) -> TokenSet:
    _require_secure(server.token_endpoint)
    payload = dict(data)
    payload["client_id"] = client.client_id
    headers = {"Accept": "application/json"}
    auth = None
    if client.client_secret and client.token_endpoint_auth_method == "client_secret_basic":
        auth = httpx.BasicAuth(client.client_id, client.client_secret)
        payload.pop("client_id", None)
    elif client.client_secret:
        payload["client_secret"] = client.client_secret
    if resource:
        payload["resource"] = resource
    provided = http_client is not None
    http = http_client or httpx.AsyncClient(timeout=timeout, follow_redirects=False)
    try:
        response = await http.post(server.token_endpoint, data=payload, headers=headers, auth=auth,
                                   follow_redirects=False)
        if response.status_code >= 400:
            raise _token_failure(response)
        return _token_set(_json_body(response))
    except httpx.HTTPError as exc:
        raise OAuthUnavailable(f"Token endpoint request failed: {exc.__class__.__name__}") from None
    finally:
        if not provided:
            await http.aclose()


def _token_failure(response: httpx.Response) -> OAuthError:
    error = ""
    try:
        body = response.json()
        if isinstance(body, dict) and isinstance(body.get("error"), str):
            error = body["error"]
    except ValueError:
        pass
    if error in ("invalid_grant", "invalid_token", "bad_refresh_token", "expired_token"):
        return OAuthReauthorizationRequired("OAuth grant was rejected; authorize this service again")
    if error in ("invalid_client", "unauthorized_client"):
        return OAuthReauthorizationRequired(
            "The OAuth client registration was rejected; register or authorize again",
            reset_client=True)
    return OAuthUnavailable(f"Token endpoint returned {response.status_code}"
                            + (f" ({error})" if error else ""))


def _token_set(body: dict) -> TokenSet:
    access_token = body.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        raise OAuthUnavailable("Token response did not contain an access_token")
    token_type = body.get("token_type")
    if not isinstance(token_type, str) or not token_type:
        token_type = "Bearer"
    refresh = body.get("refresh_token")
    scope = body.get("scope")
    expires_at = None
    expires_in = body.get("expires_in")
    if isinstance(expires_in, (int, float)) and not isinstance(expires_in, bool) and expires_in > 0:
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=float(expires_in))
    return TokenSet(
        access_token=access_token,
        token_type=token_type,
        refresh_token=refresh if isinstance(refresh, str) and refresh else None,
        expires_at=expires_at,
        scope=scope if isinstance(scope, str) else "",
    )
