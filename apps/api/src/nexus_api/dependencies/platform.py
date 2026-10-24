from __future__ import annotations

import os
from collections.abc import Iterator

from fastapi import HTTPException, Request
from sqlalchemy.orm import Session

from nexus_core.platform import Principal
from nexus_platform.errors import ServiceUnavailable
from nexus_platform.persistence.database import create_database_engine, session_factory


def get_principal(request: Request) -> Principal:
    mode = os.getenv("NEXUS_AUTH_MODE", "unconfigured").casefold()
    if mode == "development":
        # A fixed process identity supports local single-user development without trusting a client header.
        subject = os.getenv("NEXUS_DEV_USER_ID", "local-developer").strip()
        if not subject:
            raise HTTPException(status_code=503, detail="NEXUS_DEV_USER_ID is not configured")
        return Principal(id=subject, issuer="nexus-development")
    provider = getattr(request.app.state, "principal_provider", None)
    if provider is None:
        raise HTTPException(status_code=503, detail="Authentication provider is not configured")
    principal = provider(request)
    if not isinstance(principal, Principal):
        raise HTTPException(status_code=401, detail="Authentication provider returned an invalid principal")
    return principal


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
