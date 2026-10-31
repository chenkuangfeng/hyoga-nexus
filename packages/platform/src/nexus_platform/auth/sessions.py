"""Server-side login sessions. The cookie carries a random token; only its SHA-256 digest is stored."""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus_core.platform import Principal, new_id, utc_now
from nexus_platform.errors import Forbidden, Unauthenticated
from nexus_platform.persistence.models import AuthSessionRecord, UserIdentityRecord, UserRecord

SESSION_LIFETIME = timedelta(hours=12)


def aware(value: datetime) -> datetime:
    """Treat stored timestamps as UTC: SQLite returns naive datetimes for timezone-aware columns."""
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def issue_session(session: Session, user_id: UUID, identity_id: UUID) -> tuple[str, object]:
    """Create a session row and return (raw token, expiry). Call inside the caller's transaction."""
    token = secrets.token_urlsafe(32)
    now = utc_now()
    expires = now + SESSION_LIFETIME
    session.add(AuthSessionRecord(
        id=digest(token), user_id=user_id, identity_id=identity_id, created_at=now, expires_at=expires,
    ))
    return token, expires


def resolve_session(session: Session, token: str | None) -> tuple[Principal, UUID]:
    """Return the principal that logged in with this session and the internal user id."""
    if not token:
        raise Unauthenticated("Sign in is required")
    with session.begin():
        row = session.get(AuthSessionRecord, digest(token))
        if row is None or row.revoked_at is not None or aware(row.expires_at) <= utc_now():
            raise Unauthenticated("Sign in is required")
        user = session.get(UserRecord, row.user_id)
        if user is None or user.status != "active":
            raise Forbidden("The authenticated user is disabled")
        identity = session.get(UserIdentityRecord, row.identity_id)
        if identity is None:
            raise Unauthenticated("Sign in is required")
        return Principal(id=identity.external_id, issuer=identity.provider, scope=identity.scope), user.id


def revoke_session(session: Session, token: str | None) -> None:
    if not token:
        return
    with session.begin():
        row = session.get(AuthSessionRecord, digest(token))
        if row is not None and row.revoked_at is None:
            row.revoked_at = utc_now()


def revoke_user_sessions(session: Session, user_id: UUID) -> None:
    now = utc_now()
    for row in session.scalars(select(AuthSessionRecord).where(
        AuthSessionRecord.user_id == user_id, AuthSessionRecord.revoked_at.is_(None)
    )):
        row.revoked_at = now


__all__ = ["SESSION_LIFETIME", "aware", "digest", "issue_session", "resolve_session", "revoke_session", "revoke_user_sessions"]
