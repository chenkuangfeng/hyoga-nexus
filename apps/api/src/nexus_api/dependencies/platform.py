from __future__ import annotations

from collections.abc import Iterator

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from uuid import UUID

from nexus_core.platform import Principal
from nexus_platform.auth.sessions import resolve_session
from nexus_platform.configuration import AuthFileSettings, DatabaseConfigurationError, DEFAULT_DEV_USER_ID, auth_settings
from nexus_platform.auth.accounts import PASSWORD_PROVIDER
from nexus_platform.errors import Forbidden, ServiceUnavailable, Unauthenticated
from nexus_platform.persistence.database import create_database_engine, session_factory
from nexus_platform.persistence.models import UserIdentityRecord, UserRecord


def get_database_session(request: Request) -> Iterator[Session]:
    factory = getattr(request.app.state, "session_factory", None)
    if factory is None:
        try:
            from nexus_platform.runs.worker_settings import api_settings
            engine = create_database_engine(pool_size=api_settings().pool_size)
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        factory = session_factory(engine)
        request.app.state.database_engine = engine
        request.app.state.session_factory = factory
    session = factory()
    try:
        yield session
    finally:
        session.close()


def get_run_channels(request: Request):
    """Run event channels for this application.

    A process-wide installation (the embedded worker's memory bus, or a Redis bus both sides share) is
    reused so publisher and viewer see the same bus; otherwise the application builds the database bus
    over its own session factory, which keeps separate applications (and tests) on their own databases.
    """
    from nexus_platform.runs.bus import build_channels, channels
    factory = request.app.state.session_factory
    held = getattr(request.app.state, "run_channels", None)
    shared = channels()
    if shared is not None and shared.bus.name != "database":
        held = request.app.state.run_channels = shared
    elif held is None or getattr(request.app.state, "run_channels_factory", None) is not factory:
        # Rebuilt when the application's session factory changes (separate databases in tests).
        held = request.app.state.run_channels = build_channels(factory)
        request.app.state.run_channels_factory = factory
    return held


SESSION_COOKIE = "nexus_session"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
# Cookie-authenticated writes must carry this header. Browsers cannot send it cross-site without a
# CORS preflight, so it blocks forged form posts that would ride on the session cookie.
CSRF_HEADER = "X-Nexus-Request"
# The space the client works in (WeKnora's convention). The server checks membership on every request.
TENANT_HEADER = "X-Tenant-ID"
# Paths a user must still be able to call while the initial password is not yet changed.
PASSWORD_CHANGE_PATHS = frozenset({
    "/api/v1/auth/me", "/api/v1/auth/logout", "/api/v1/auth/change-password", "/api/v1/auth/password",
})


def _auth_file_settings() -> AuthFileSettings:
    """Read ``[auth]`` from configs/nexus.toml; a malformed file fails closed with 503."""
    try:
        return auth_settings()
    except DatabaseConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def development_identity(db: Session, settings: AuthFileSettings) -> UserIdentityRecord:
    """The existing password identity that development mode acts as (`[auth].dev_user_id`, a username).

    Development mode never creates accounts: the identity must already exist, normally the default owner
    bootstrapped at API start. Raises 503 with the fix when it is missing.
    """
    username = (settings.dev_user_id or DEFAULT_DEV_USER_ID).strip()
    # Run the lookup in its own transaction: later handlers call session.begin() on this request's session,
    # which would fail if a transaction were already open from the implicit autobegin.
    with db.begin():
        identity = db.scalar(select(UserIdentityRecord).where(
            UserIdentityRecord.provider == PASSWORD_PROVIDER,
            UserIdentityRecord.scope == "",
            UserIdentityRecord.external_id == username,
        ))
    if identity is None:
        raise HTTPException(
            status_code=503,
            detail=f"Development mode: no password account named {username!r}; set [auth].dev_user_id to an existing username",
        )
    return identity


def get_principal(request: Request, db: Session = Depends(get_database_session)) -> Principal:
    settings = _auth_file_settings()
    mode = (settings.mode or "unconfigured").casefold()
    if mode == "development":
        # Local development acts as one existing account on every request; the loopback guard keeps this off
        # the network. Accounts are never created here.
        identity = development_identity(db, settings)
        return Principal(id=identity.external_id, issuer=identity.provider, scope=identity.scope)
    provider = getattr(request.app.state, "principal_provider", None)
    if mode not in {"session", "external"} and provider is None:
        raise HTTPException(status_code=503, detail="Authentication provider is not configured")
    bearer = bearer_token(request)
    if bearer is not None:
        # Bearer tokens are not sent by browsers on their own, so they need no CSRF header.
        principal, user_id = resolve_session(db, bearer)
        _enforce_password_change(request, db, user_id)
        return principal
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        if request.method not in SAFE_METHODS and request.headers.get(CSRF_HEADER) != "1":
            raise Forbidden("Missing request header for a session-authenticated write")
        principal, user_id = resolve_session(db, token)
        _enforce_password_change(request, db, user_id)
        return principal
    if provider is None:
        raise Unauthenticated("Sign in is required")
    principal = provider(request)
    if not isinstance(principal, Principal):
        raise HTTPException(status_code=401, detail="Authentication provider returned an invalid principal")
    return principal


def bearer_token(request: Request) -> str | None:
    """The token from `Authorization: Bearer <token>`, or None when the header is absent or not Bearer."""
    header = request.headers.get("Authorization", "")
    scheme, _, value = header.partition(" ")
    if scheme.casefold() != "bearer" or not value.strip():
        return None
    return value.strip()


def _enforce_password_change(request: Request, db: Session, user_id: UUID) -> None:
    """A user with a temporary password may only change it, read `/auth/me` and sign out."""
    with db.begin():
        user = db.get(UserRecord, user_id)
        pending = user is not None and user.must_change_password
    if pending and request.url.path not in PASSWORD_CHANGE_PATHS:
        raise Forbidden("Change your initial password before continuing")


def get_tenant_header(request: Request) -> UUID | None:
    """The space named by `X-Tenant-ID`, or None when the client did not send one. Malformed values are rejected."""
    raw = request.headers.get(TENANT_HEADER)
    if raw is None or not raw.strip():
        return None
    try:
        return UUID(raw.strip())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="X-Tenant-ID must be a UUID") from exc
