from __future__ import annotations

from collections.abc import Iterator

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from nexus_core.platform import Principal
from nexus_platform.auth.sessions import resolve_session
from nexus_platform.configuration import AuthFileSettings, DatabaseConfigurationError, DEFAULT_DEV_USER_ID, auth_settings
from nexus_platform.errors import Forbidden, ServiceUnavailable, Unauthenticated
from nexus_platform.persistence.database import create_database_engine, session_factory


def get_database_session(request: Request) -> Iterator[Session]:
    factory = getattr(request.app.state, "session_factory", None)
    if factory is None:
        try:
            engine = create_database_engine()
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


SESSION_COOKIE = "nexus_session"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
# Cookie-authenticated writes must carry this header. Browsers cannot send it cross-site without a
# CORS preflight, so it blocks forged form posts that would ride on the session cookie.
CSRF_HEADER = "X-Nexus-Request"


def _auth_file_settings() -> AuthFileSettings:
    """Read ``[auth]`` from configs/nexus.toml; a malformed file fails closed with 503."""
    try:
        return auth_settings()
    except DatabaseConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def get_principal(request: Request, db: Session = Depends(get_database_session)) -> Principal:
    settings = _auth_file_settings()
    mode = (settings.mode or "unconfigured").casefold()
    if mode == "development":
        # A fixed process identity supports local single-user development without trusting a client header.
        subject = (settings.dev_user_id or DEFAULT_DEV_USER_ID).strip()
        return Principal(id=subject, issuer="nexus-development")
    provider = getattr(request.app.state, "principal_provider", None)
    if mode not in {"session", "external"} and provider is None:
        raise HTTPException(status_code=503, detail="Authentication provider is not configured")
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        if request.method not in SAFE_METHODS and request.headers.get(CSRF_HEADER) != "1":
            raise Forbidden("Missing request header for a session-authenticated write")
        principal, _ = resolve_session(db, token)
        return principal
    if provider is None:
        raise Unauthenticated("Sign in is required")
    principal = provider(request)
    if not isinstance(principal, Principal):
        raise HTTPException(status_code=401, detail="Authentication provider returned an invalid principal")
    return principal
