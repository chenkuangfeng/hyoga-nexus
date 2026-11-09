"""Per-principal OAuth for MCP services: authorization flow, encrypted token storage and refresh.

Tokens are scoped by (tenant, principal, service) and encrypted with the deployment key, so no
secret is ever persisted in plaintext. A refresh happens lazily before use (30 s skew) and on a
single 401 from the resource server; a rejected grant deletes the token and surfaces
``mcp_oauth_required`` so the caller asks the user to authorize again. Authorization `state`
is an encrypted, expiring payload carrying the PKCE verifier, so no extra table is needed and
the verifier never reaches the browser.

Cross-process refresh races are narrowed with a row lock where the database supports it
(PostgreSQL); a rotating grant may still be consumed twice on databases that ignore
``SELECT ... FOR UPDATE`` (SQLite), which presents as a re-authorization prompt rather than a
silent credential leak.
"""
from __future__ import annotations

import asyncio
import json
from datetime import timedelta
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus_core.platform import Principal, new_id, utc_now
from nexus_platform.authz.audit import audit
from nexus_platform.errors import InvalidConfiguration, NotFound, PlatformError, ServiceUnavailable
from nexus_platform.persistence.models import McpOAuthClientRecord, McpOAuthTokenRecord, McpServiceRecord
from nexus_platform.identity.service import require_membership, require_tenant, resolve_user
from nexus_mcp import oauth as mcp_oauth

from .common import RESOURCE_KIND, aware

#: Refresh this long before the access token actually expires, so a call never starts with a dead one.
REFRESH_SKEW = timedelta(seconds=30)
#: How long a browser may take between "authorize" and the callback.
STATE_TTL = timedelta(minutes=10)
#: Fixed binding prefix for the encrypted state: a state sealed for another purpose cannot be replayed.
_STATE_BINDING = "mcp-oauth-state-v1"


class McpOAuthRequired(PlatformError):
    """No usable token is stored (or the grant was revoked); the user must authorize the service."""

    code = "mcp_oauth_required"
    status_code = 403


class McpOAuthStateInvalid(PlatformError):
    """The callback state is missing, malformed, or was not issued by this deployment."""

    code = "mcp_oauth_state_invalid"
    status_code = 400

    def __init__(self, message: str = "MCP OAuth state is invalid or was not issued here"):
        super().__init__(message)


class McpOAuthStateExpired(McpOAuthStateInvalid):
    """The callback arrived after the authorization window closed; start the flow again."""

    code = "mcp_oauth_state_expired"

    def __init__(self, message: str = "MCP OAuth state has expired; authorize the service again"):
        super().__init__(message)


def _cipher():
    # Imported lazily: the platform package's model settings module imports many services, and this
    # module must stay importable while those initialise.
    from nexus_platform.models.provider_settings import cipher
    return cipher()


def _seal(value: str, binding: str) -> str:
    """Encrypt `value` bound to its row identity, so ciphertext cannot be swapped between rows."""
    return _cipher().encrypt((binding + "\n" + value).encode()).decode()


def _open(token: str, binding: str) -> str:
    from cryptography.fernet import InvalidToken
    try:
        text = _cipher().decrypt(token.encode()).decode()
        stored_binding, value = text.split("\n", 1)
        if stored_binding != binding:
            raise InvalidToken
        return value
    except (InvalidToken, ValueError, UnicodeError):
        raise ServiceUnavailable("Stored OAuth credential cannot be decrypted") from None


def _token_binding(tenant_id: UUID, principal_id: UUID, service_id: UUID) -> str:
    return f"mcp-oauth-token:{tenant_id}:{principal_id}:{service_id}"


def _client_binding(tenant_id: UUID, service_id: UUID) -> str:
    return f"mcp-oauth-client:{tenant_id}:{service_id}"


def _settings(service: McpServiceRecord) -> dict[str, Any]:
    oauth = (service.config or {}).get("oauth")
    return oauth if isinstance(oauth, dict) else {}


def _require_oauth(service: McpServiceRecord) -> dict[str, Any]:
    if service.config.get("auth_type") != "oauth":
        raise InvalidConfiguration("mcp_oauth_not_configured")
    return _settings(service)


def _validate_redirect_uri(value: str) -> str:
    """The backend callback URL registered with the authorization server: absolute HTTP(S)."""
    if not isinstance(value, str) or not value or len(value) > 1024:
        raise InvalidConfiguration("mcp_oauth_redirect_uri_invalid")
    parsed = urlsplit(value)
    if parsed.scheme not in ("http", "https") or not parsed.netloc or parsed.fragment:
        raise InvalidConfiguration("mcp_oauth_redirect_uri_invalid")
    if any(char in value for char in "\\\r\n\t"):
        raise InvalidConfiguration("mcp_oauth_redirect_uri_invalid")
    return value


def _validate_frontend_redirect(value: str | None) -> str:
    """Only an application-relative path: the callback is public, so never redirect off-origin."""
    if not value:
        return "/"
    if not isinstance(value, str) or len(value) > 2048 or any(char in value for char in "\\\r\n\t"):
        raise InvalidConfiguration("mcp_oauth_frontend_redirect_invalid")
    if not value.startswith("/") or value.startswith("//"):
        raise InvalidConfiguration("mcp_oauth_frontend_redirect_invalid")
    return value


def _context(db: Session, principal: Principal, tenant_id: UUID):
    user = resolve_user(db, principal)
    require_tenant(db, tenant_id)
    require_membership(db, tenant_id, user.id)
    return user


def _load_service(db: Session, tenant_id: UUID, service_id: UUID) -> McpServiceRecord:
    service = db.get(McpServiceRecord, service_id)
    if service is None or service.tenant_id != tenant_id:
        raise NotFound("MCP service not found")
    return service


def _load_client(db: Session, tenant_id: UUID, service_id: UUID) -> McpOAuthClientRecord | None:
    return db.scalar(select(McpOAuthClientRecord).where(
        McpOAuthClientRecord.tenant_id == tenant_id, McpOAuthClientRecord.service_id == service_id))


def frontend_redirect_for(state: str) -> str:
    """Best-effort SPA return path for a callback redirect; ``"/"`` when the state cannot be trusted.

    Deliberately ignores expiry: an expired authorization should still send the browser back to the
    page that started it, so the UI can explain the failure. Only a relative path is ever returned.
    """
    try:
        payload = json.loads(_open(state, _STATE_BINDING))
    except (PlatformError, ValueError, TypeError):
        return "/"
    if not isinstance(payload, dict):
        return "/"
    try:
        return _validate_frontend_redirect(payload.get("frontend_redirect"))
    except PlatformError:
        return "/"


def _client_for(settings: dict[str, Any], row: McpOAuthClientRecord | None) -> mcp_oauth.OAuthClient:
    """Prefer the operator's pre-registered client, then a stored dynamic registration."""
    client_id = settings.get("client_id")
    if isinstance(client_id, str) and client_id:
        secret = settings.get("client_secret")
        # The redirect URI always comes from the authorization request/state, never from a stale row.
        return mcp_oauth.OAuthClient(client_id=client_id,
                                     client_secret=secret if isinstance(secret, str) else None,
                                     metadata_url=settings.get("auth_server_metadata_url") or "")
    if row is None:
        raise McpOAuthRequired("MCP OAuth client is not registered; authorize the service first")
    secret = _open(row.client_secret, _client_binding(row.tenant_id, row.service_id)) \
        if row.client_secret else None
    return mcp_oauth.OAuthClient(client_id=row.client_id, client_secret=secret,
                                 redirect_uri=row.redirect_uri, metadata_url=row.auth_server_metadata_url)


def _discover(service: McpServiceRecord, settings: dict[str, Any]) -> mcp_oauth.AuthorizationServer:
    metadata_url = settings.get("auth_server_metadata_url")
    try:
        return asyncio.run(mcp_oauth.discover(
            service.config["url"],
            metadata_url=metadata_url if isinstance(metadata_url, str) and metadata_url else None))
    except mcp_oauth.OAuthConfigurationError as exc:
        raise InvalidConfiguration(exc.code) from None
    except mcp_oauth.OAuthError as exc:
        raise ServiceUnavailable(exc.code) from None


def _ensure_client(db: Session, service: McpServiceRecord, settings: dict[str, Any],
                   server: mcp_oauth.AuthorizationServer, redirect_uri: str) -> mcp_oauth.OAuthClient:
    """Reuse a pre-registered/stored client, or dynamically register one exactly once."""
    if isinstance(settings.get("client_id"), str) and settings.get("client_id"):
        return _client_for(settings, None)
    row = _load_client(db, service.tenant_id, service.id)
    if row is not None:
        return _client_for(settings, row)
    try:
        registered = asyncio.run(mcp_oauth.register_client(
            server, redirect_uri, scopes=tuple(settings.get("scopes") or [])))
    except mcp_oauth.OAuthConfigurationError as exc:
        raise InvalidConfiguration(exc.code) from None
    except mcp_oauth.OAuthError as exc:
        raise ServiceUnavailable(exc.code) from None
    now = utc_now()
    db.add(McpOAuthClientRecord(
        id=new_id(),
        tenant_id=service.tenant_id, service_id=service.id,
        client_id=registered.client_id,
        client_secret=_seal(registered.client_secret, _client_binding(service.tenant_id, service.id))
        if registered.client_secret else None,
        redirect_uri=redirect_uri,
        auth_server_metadata_url=server.metadata_url,
        registration_access_token=None, updated_at=now,
    ))
    db.flush()
    return registered


# --------------------------------------------------------------------------- authorization flow

def begin_authorization(db: Session, principal: Principal, tenant_id: UUID, service_id: UUID, *,
                        redirect_uri: str, frontend_redirect: str | None = None) -> dict[str, Any]:
    """Start the authorization-code + PKCE flow and return the URL the browser must open.

    Any active member may authorize a service for their own principal; the resulting token is
    private to them. Dynamic client registration is stored per (tenant, service) and reused.
    """
    with db.begin():
        user = _context(db, principal, tenant_id)
        service = _load_service(db, tenant_id, service_id)
        settings = _require_oauth(service)
        redirect_uri = _validate_redirect_uri(redirect_uri)
        frontend = _validate_frontend_redirect(frontend_redirect)
        server = _discover(service, settings)
        client = _ensure_client(db, service, settings, server, redirect_uri)
        verifier, challenge = mcp_oauth.generate_pkce()
        state = _seal(json.dumps({
            "v": 1, "tenant_id": str(tenant_id), "principal_id": str(user.id),
            "service_id": str(service_id), "code_verifier": verifier,
            "redirect_uri": redirect_uri, "frontend_redirect": frontend,
            "expires_at": (utc_now() + STATE_TTL).timestamp(),
        }, separators=(",", ":")), _STATE_BINDING)
        url = mcp_oauth.authorization_url(
            server, client.client_id, redirect_uri, state=state, code_challenge=challenge,
            scopes=tuple(settings.get("scopes") or ()), resource=service.config.get("url"))
        return {"authorization_url": url, "state": state}


def _state_payload(state: str) -> dict[str, Any]:
    try:
        payload = json.loads(_open(state, _STATE_BINDING))
    except (ServiceUnavailable, ValueError, TypeError):
        # Undecryptable is indistinguishable from forged: both mean "not issued by this deployment".
        raise McpOAuthStateInvalid() from None
    if not isinstance(payload, dict) or payload.get("v") != 1:
        raise McpOAuthStateInvalid()
    try:
        expires_at = float(payload["expires_at"])
        for key in ("tenant_id", "principal_id", "service_id", "code_verifier", "redirect_uri"):
            if not isinstance(payload[key], str):
                raise ValueError
    except (KeyError, TypeError, ValueError):
        raise McpOAuthStateInvalid() from None
    if expires_at <= utc_now().timestamp():
        raise McpOAuthStateExpired()
    return payload


def complete_authorization(db: Session, state: str, code: str) -> dict[str, Any]:
    """Exchange a callback code for the principal's token and store it encrypted.

    Returns the tenant/service/principal and the validated frontend redirect so the caller can
    send the browser back and recycle any cached connection built with the old credential.
    """
    payload = _state_payload(state)
    tenant_id = UUID(payload["tenant_id"])
    service_id = UUID(payload["service_id"])
    principal_id = UUID(payload["principal_id"])
    frontend = _validate_frontend_redirect(payload.get("frontend_redirect"))
    with db.begin():
        service = _load_service(db, tenant_id, service_id)
        settings = _require_oauth(service)
        server = _discover(service, settings)
        client = _client_for(settings, _load_client(db, tenant_id, service_id))
        if not client.redirect_uri:
            client = mcp_oauth.OAuthClient(client_id=client.client_id,
                                           client_secret=client.client_secret,
                                           redirect_uri=payload["redirect_uri"],
                                           metadata_url=client.metadata_url,
                                           token_endpoint_auth_method=client.token_endpoint_auth_method)
        try:
            tokens = asyncio.run(mcp_oauth.exchange_code(
                server, client, code=code, code_verifier=payload["code_verifier"],
                redirect_uri=payload["redirect_uri"], resource=service.config.get("url")))
        except mcp_oauth.OAuthReauthorizationRequired as exc:
            raise McpOAuthRequired(exc.code) from None
        except mcp_oauth.OAuthError as exc:
            raise ServiceUnavailable(exc.code) from None
        _store_tokens(db, service, principal_id, tokens)
        audit(db, tenant_id, principal_id, "mcp_service.oauth_authorized", RESOURCE_KIND, str(service_id), {})
    return {"tenant_id": tenant_id, "service_id": service_id, "principal_id": principal_id,
            "frontend_redirect": frontend}


def authorization_status(db: Session, principal: Principal, tenant_id: UUID, service_id: UUID) -> dict[str, Any]:
    """Report whether this principal's token is usable now, refreshable, or missing."""
    with db.begin():
        user = _context(db, principal, tenant_id)
        _load_service(db, tenant_id, service_id)
        row = _token_row(db, tenant_id, user.id, service_id)
    return _status_of(row)


def _status_of(row: McpOAuthTokenRecord | None) -> dict[str, Any]:
    if row is None:
        return {"authorized": False, "state": "reauth_required", "refresh_available": False}
    refresh_available = bool(row.refresh_token)
    status: dict[str, Any] = {"authorized": False, "refresh_available": refresh_available}
    if row.expires_at is not None:
        status["expires_at"] = aware(row.expires_at).isoformat()
    if row.expires_at is None or aware(row.expires_at) > utc_now():
        status.update(authorized=True, state="authorized")
    elif refresh_available:
        status["state"] = "refreshable"
    else:
        status["state"] = "reauth_required"
    return status


def revoke_authorization(db: Session, principal: Principal, tenant_id: UUID, service_id: UUID) -> None:
    """Delete this principal's token; the next call asks for authorization again."""
    with db.begin():
        user = _context(db, principal, tenant_id)
        row = _token_row(db, tenant_id, user.id, service_id)
        if row is not None:
            db.delete(row)
            audit(db, tenant_id, user.id, "mcp_service.oauth_revoked", RESOURCE_KIND, str(service_id), {})


# --------------------------------------------------------------------------- token use

def _token_row(db: Session, tenant_id: UUID, principal_id: UUID, service_id: UUID, *,
               lock: bool = False, refresh: bool = False) -> McpOAuthTokenRecord | None:
    statement = select(McpOAuthTokenRecord).where(
        McpOAuthTokenRecord.tenant_id == tenant_id,
        McpOAuthTokenRecord.principal_id == principal_id,
        McpOAuthTokenRecord.service_id == service_id)
    if lock:
        statement = statement.with_for_update()
    if refresh:
        # Re-read current values: the identity map alone would return the stale pre-lock snapshot.
        statement = statement.execution_options(populate_existing=True)
    return db.scalar(statement)


def _usable(row: McpOAuthTokenRecord) -> bool:
    """True when the stored access token is far enough from expiry to be presented."""
    return row.expires_at is None or aware(row.expires_at) > utc_now() + REFRESH_SKEW


def _forget(db: Session, *rows) -> None:
    """Delete dead credentials and commit now, before ``McpOAuthRequired`` unwinds the caller.

    Callers resolve tokens inside their own transaction (``resolve_call``, ``discover_tools``), and
    that transaction rolls back when the error propagates; without this commit the rejected grant
    would survive and be retried on every call instead of prompting for authorization again.
    """
    for row in rows:
        db.delete(row)
    db.commit()


def _store_tokens(db: Session, service: McpServiceRecord, principal_id: UUID,
                  tokens: mcp_oauth.TokenSet) -> McpOAuthTokenRecord:
    row = _token_row(db, service.tenant_id, principal_id, service.id, lock=True)
    binding = _token_binding(service.tenant_id, principal_id, service.id)
    now = utc_now()
    if row is None:
        row = McpOAuthTokenRecord(
            tenant_id=service.tenant_id, principal_id=principal_id, service_id=service.id,
            access_token="", refresh_token=None, expires_at=None, scope="", updated_at=now)
        db.add(row)
    row.access_token = _seal(tokens.access_token, binding)
    # A missing refresh token is stored as absent; the refresh path reuses the prior one explicitly
    # (RFC 6749 §6), a fresh authorization replaces the grant wholesale.
    row.refresh_token = _seal(tokens.refresh_token, binding) if tokens.refresh_token else None
    row.expires_at = tokens.expires_at
    row.scope = tokens.scope
    row.updated_at = now
    db.flush()
    return row


def access_token(db: Session, tenant_id: UUID, principal_id: UUID, service: McpServiceRecord, *,
                 force_refresh: bool = False) -> str:
    """Return a usable access token, refreshing it (once) when expiring; never returns a secret.

    Raises `McpOAuthRequired` when no token exists or the grant was rejected, and
    `ServiceUnavailable('mcp_oauth_unavailable')` for transient token-endpoint failures.
    """
    row = _token_row(db, tenant_id, principal_id, service.id)
    if row is None:
        raise McpOAuthRequired("MCP service requires OAuth authorization")
    binding = _token_binding(tenant_id, principal_id, service.id)
    access = _open(row.access_token, binding)
    if not force_refresh and _usable(row):
        return access
    # Serialise concurrent refreshes where the database supports row locks (PostgreSQL). Re-read
    # under the lock so a rotation another process completed while we waited is observed instead of
    # refreshing a refresh token that was already consumed.
    locked = _token_row(db, tenant_id, principal_id, service.id, lock=True, refresh=True)
    if locked is None:
        raise McpOAuthRequired("MCP service requires OAuth authorization")
    row = locked
    rotated = _open(row.access_token, binding)
    if not force_refresh and rotated != access and _usable(row):
        return rotated
    refresh = _open(row.refresh_token, binding) if row.refresh_token else None
    if not refresh:
        _forget(db, row)
        raise McpOAuthRequired("MCP OAuth token expired and cannot be refreshed")
    settings = _require_oauth(service)
    server = _discover(service, settings)
    client = _client_for(settings, _load_client(db, tenant_id, service.id))
    try:
        tokens = asyncio.run(mcp_oauth.refresh_token(
            server, client, refresh, resource=service.config.get("url")))
    except mcp_oauth.OAuthReauthorizationRequired as exc:
        dead = [row]
        if exc.reset_client:
            registered = _load_client(db, tenant_id, service.id)
            if registered is not None:
                dead.append(registered)
        _forget(db, *dead)
        raise McpOAuthRequired("MCP OAuth authorization must be renewed") from None
    except mcp_oauth.OAuthError as exc:
        raise ServiceUnavailable(exc.code) from None
    if tokens.refresh_token is None:
        # RFC 6749 §6: a refresh response may omit refresh_token; keep the prior one.
        tokens = mcp_oauth.TokenSet(
            access_token=tokens.access_token, token_type=tokens.token_type,
            refresh_token=refresh, expires_at=tokens.expires_at, scope=tokens.scope)
    _store_tokens(db, service, principal_id, tokens)
    # A rotating server may invalidate the old refresh token immediately, so the new grant is
    # committed now: a failure later in the caller's transaction must not roll the rotation away.
    db.commit()
    return tokens.access_token


def authorization_value(db: Session, tenant_id: UUID, principal_id: UUID,
                        service: McpServiceRecord, *, force_refresh: bool = False) -> str:
    """The `Authorization` header value for a connection, refreshing first when needed."""
    return f"Bearer {access_token(db, tenant_id, principal_id, service, force_refresh=force_refresh)}"
