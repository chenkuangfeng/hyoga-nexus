"""WeCom QR login and account binding for one internal corp application.

The HTTP exchange with WeCom sits behind `WeComDirectory`, so the platform keeps no network code
and tests can substitute a fake. Flow:
- login: a one-time `login` state is issued; the callback exchanges the code for `userid` and
  opens a session only when `(wecom, corp_id, userid)` is already bound to a user;
- bind: a signed-in user receives a one-time `bind` state tied to their user id; the callback
  links `(wecom, corp_id, userid)` to that user unless another user already holds it.
Unbound WeCom users are never created automatically.
"""
from __future__ import annotations

import secrets
from datetime import timedelta
from typing import Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus_core.platform import Principal, new_id, utc_now
from nexus_platform.auth.sessions import aware, digest, issue_session
from nexus_platform.authz.audit import audit
from nexus_platform.errors import Conflict, Forbidden, Unauthenticated
from nexus_platform.identity.service import resolve_user
from nexus_platform.persistence.models import AuthStateRecord, MembershipRecord, TenantRecord, UserIdentityRecord, UserRecord

WECOM_PROVIDER = "wecom"
STATE_LIFETIME = timedelta(minutes=10)
UNBOUND_MESSAGE = "该企业微信账号尚未绑定空间账号，请先使用账号密码登录，再在设置中绑定企业微信"


class WeComDirectory(Protocol):
    """Adapter to WeCom: build the QR authorization URL and resolve a callback code."""

    corp_id: str

    def authorize_url(self, state: str) -> str: ...

    def resolve_user(self, code: str) -> str:
        """Return the corp member `userid` for a callback code. Raises Unauthenticated on failure."""
        ...


def _issue_state(session: Session, purpose: str, user_id: UUID | None) -> str:
    raw = secrets.token_urlsafe(32)
    now = utc_now()
    with session.begin():
        session.add(AuthStateRecord(
            id=digest(raw), purpose=purpose, user_id=user_id, created_at=now, expires_at=now + STATE_LIFETIME,
        ))
    return raw


def _consume_state(session: Session, raw: str | None, purpose: str) -> AuthStateRecord:
    """Mark a state as used; expired, reused or wrong-purpose states are rejected."""
    if not raw:
        raise Unauthenticated("登录已失效，请重新发起")
    now = utc_now()
    row = session.get(AuthStateRecord, digest(raw))
    if row is None or row.purpose != purpose or row.consumed_at is not None or aware(row.expires_at) <= now:
        raise Unauthenticated("登录已失效，请重新发起")
    row.consumed_at = now
    return row


def start_login(session: Session) -> str:
    """Issue a login state for the QR flow and return it for the authorization URL."""
    return _issue_state(session, "login", None)


def start_binding(session: Session, principal: Principal) -> str:
    """Issue a bind state for a signed-in user. The caller must already be authenticated."""
    with session.begin():
        user = resolve_user(session, principal)
        user_id = user.id
    return _issue_state(session, "bind", user_id)


def login_with_wecom(session: Session, directory: WeComDirectory, *, code: str, state: str,
                     corp_id: str) -> tuple[str, object, UUID]:
    """Finish QR login. Returns (raw session token, expiry, user id) for a bound WeCom user."""
    with session.begin():
        _consume_state(session, state, "login")
    userid = directory.resolve_user(code)
    with session.begin():
        identity = session.scalar(select(UserIdentityRecord).where(
            UserIdentityRecord.provider == WECOM_PROVIDER,
            UserIdentityRecord.scope == corp_id,
            UserIdentityRecord.external_id == userid,
        ))
        user = session.get(UserRecord, identity.user_id) if identity else None
        if identity is None or user is None:
            raise Forbidden(UNBOUND_MESSAGE)
        if user.status != "active":
            raise Forbidden("The authenticated user is disabled")
        token, expires = issue_session(session, user.id, identity.id)
    return token, expires, user.id


def bind_wecom(session: Session, directory: WeComDirectory, *, code: str, state: str, corp_id: str,
               expected_user_id: UUID) -> None:
    """Link the WeCom member behind `code` to the user that started the binding."""
    with session.begin():
        row = _consume_state(session, state, "bind")
        if row.user_id != expected_user_id:
            raise Unauthenticated("登录已失效，请重新发起")
    userid = directory.resolve_user(code)
    now = utc_now()
    with session.begin():
        existing = session.scalar(select(UserIdentityRecord).where(
            UserIdentityRecord.provider == WECOM_PROVIDER,
            UserIdentityRecord.scope == corp_id,
            UserIdentityRecord.external_id == userid,
        ))
        if existing is not None:
            if existing.user_id != expected_user_id:
                raise Conflict("该企业微信账号已绑定其他用户")
            return
        # A corp recorded on an enterprise space may only be bound by that enterprise's members.
        corp_spaces = list(session.scalars(select(TenantRecord.id).where(TenantRecord.wecom_corp_id == corp_id)))
        if corp_spaces:
            member_of = session.scalar(select(MembershipRecord.tenant_id).where(
                MembershipRecord.user_id == expected_user_id,
                MembershipRecord.tenant_id.in_(corp_spaces),
                MembershipRecord.status == "active",
            ).limit(1))
            if member_of is None:
                raise Forbidden("该企业微信企业只能绑定本企业成员账号")
        session.add(UserIdentityRecord(
            id=new_id(), user_id=expected_user_id, provider=WECOM_PROVIDER, scope=corp_id,
            external_id=userid, verified_at=now, created_at=now,
        ))
        # Audit rows belong to a tenant; a user without tenant membership has nothing to audit against.
        tenant_id = session.scalar(
            select(MembershipRecord.tenant_id).where(MembershipRecord.user_id == expected_user_id).limit(1)
        )
        if tenant_id is not None:
            audit(session, tenant_id, expected_user_id, "user.wecom_bound", "user", str(expected_user_id))


def state_purpose(session: Session, raw: str | None) -> str | None:
    """Return the purpose of a live, unused state without consuming it (used to route callbacks)."""
    if not raw:
        return None
    # An explicit transaction keeps the session free for the begin() blocks that follow.
    with session.begin():
        row = session.get(AuthStateRecord, digest(raw))
        if row is None or row.consumed_at is not None or aware(row.expires_at) <= utc_now():
            return None
        return row.purpose
