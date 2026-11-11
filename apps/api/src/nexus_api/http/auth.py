"""Authentication routes: self-service sign-up, email sign-in, space switching, the current user and password change.

Sign-in returns a Bearer token (`Authorization: Bearer <token>`) that the web client stores and sends with
every request, as WeKnora does. The same token is also set as an HttpOnly cookie for browser flows
(WeCom redirects). Cookie-authenticated writes need the X-Nexus-Request header; Bearer requests do not.
The current space is chosen with the `X-Tenant-ID` header and checked against memberships on each request.
Cookies are Secure unless ``[auth].cookie_secure = false`` (local HTTP development only).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus_core.platform import Principal, TenantRole
from nexus_platform.auth import accounts, preferences, sessions, wecom
from nexus_platform.configuration import auth_settings
from nexus_platform.errors import Conflict, Forbidden, NotFound, Unauthenticated
from nexus_platform.identity.service import resolve_user
from nexus_platform.persistence.models import TenantRecord, UserIdentityRecord, UserRecord
from nexus_platform.tenants import service as tenants
from nexus_api.dependencies.platform import (
    CSRF_HEADER, SESSION_COOKIE, bearer_token, development_identity, get_database_session, get_principal, get_tenant_header,
)
from nexus_api.http.wecom_directory import HttpWeComDirectory

router = APIRouter(prefix="/api/v1/auth", tags=["Authentication"])


class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=10, max_length=256)
    #: Ignored: every registration creates an enterprise (openspec 2026-11-11-enterprise-saas). Kept for old clients.
    space_kind: str = Field(default="enterprise", pattern="^(personal|enterprise)$")
    space_name: str = Field(default="", max_length=160)
    company_code: str = Field(default="", max_length=32)
    display_name: str = Field(default="", max_length=160)


class EmailLogin(BaseModel):
    email: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=1, max_length=256)


class SwitchTenant(BaseModel):
    tenant_id: UUID


class PreferencesUpdate(BaseModel):
    """Partial update: only the fields sent are changed. `last_active_tenant_id: null` clears it.
    Unknown keys are rejected (422) so typos do not silently do nothing."""

    model_config = ConfigDict(extra="forbid")

    last_active_tenant_id: str | None = Field(default=None, max_length=64)
    browser_search_instructions: str | None = Field(default=None, max_length=4000)
    gallery: dict[str, Any] | None = None


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=10, max_length=256)


def _cookie_secure() -> bool:
    """Read from the deployment file; a malformed file raises a configuration error (fails closed)."""
    return auth_settings().cookie_secure


def _set_session(response: Response, token: str, expires: datetime) -> None:
    response.set_cookie(
        SESSION_COOKIE, token, httponly=True, samesite="lax", secure=_cookie_secure(),
        expires=expires, path="/",
    )


def _directory(request: Request):
    override = getattr(request.app.state, "wecom_directory", None)
    return override if override is not None else HttpWeComDirectory.from_configuration()


def _require_csrf(request: Request) -> None:
    if request.headers.get(CSRF_HEADER) != "1":
        raise Forbidden("Missing request header for a session-authenticated write")


def _space_view(tenant: TenantRecord, role: str) -> dict:
    """One space the user belongs to, in the shape of WeKnora's membership (`tenant_id`, `tenant_name`)."""
    return {"id": tenant.id, "tenant_id": tenant.id, "name": tenant.name, "tenant_name": tenant.name,
            "kind": tenant.kind, "role": role}


def _user_view(db: Session, user: UserRecord) -> dict:
    identities = db.execute(select(UserIdentityRecord.provider, UserIdentityRecord.external_id).where(
        UserIdentityRecord.user_id == user.id)).all()
    username = next((ext for prov, ext in identities if prov == accounts.PASSWORD_PROVIDER), None)
    return {
        "id": user.id, "username": username, "email": user.email, "display_name": user.display_name,
        "providers": sorted({prov for prov, _ in identities}),
        "is_platform_admin": user.is_platform_admin, "must_change_password": user.must_change_password,
        "preferences": dict(user.preferences or {}),
    }


def _tenant_info(space: dict) -> dict:
    """The space in the shape the web client expects for `tenant` (fields it does not track are neutral)."""
    return {"id": space["id"], "name": space["name"], "description": "", "status": "active", "business": "",
            "kind": space["kind"], "storage_quota": 0, "storage_used": 0, "created_at": None, "updated_at": None}


def _memberships(db: Session, principal: Principal) -> list[dict]:
    return [_space_view(tenant, role) for tenant, role in tenants.list_tenants(db, principal)]


@router.get("/config")
def auth_config():
    """Public sign-in options for the login page. Self-service sign-up is `self_serve` or `invite_only`."""
    return {
        "success": True,
        "registration_mode": "self_serve" if auth_settings().registration_enabled else "invite_only",
        "complex_password_enabled": True,
        # True in development mode: the web client may call /auth/dev-session instead of showing the form.
        "development_login": (auth_settings().mode or "").casefold() == "development",
    }


@router.get("/oidc/config")
def oidc_config():
    """OIDC is not provided by this deployment; the login page then shows only email sign-in."""
    return {"success": True, "enabled": False}


@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(body: RegisterRequest, request: Request, db: Session = Depends(get_database_session)):
    """Create an account with its first space. Personal spaces need no code; enterprises need a unique code."""
    user, space = accounts.register(
        db, username=body.username, email=body.email, password=body.password, space_kind=body.space_kind,
        space_name=body.space_name, company_code=body.company_code, display_name=body.display_name,
        allow_registration=auth_settings().registration_enabled,
    )
    return {
        "success": True,
        "data": {
            "user": {"id": user.id, "email": user.email, "display_name": user.display_name},
            "tenant": {"id": space.id, "name": space.name, "kind": space.kind},
        },
    }


@router.post("/login")
def login(body: EmailLogin, request: Request, response: Response, db: Session = Depends(get_database_session)):
    """Sign in with email and password. The response lists the spaces the user may enter; the client picks one."""
    token, expires, user_id = accounts.authenticate_email(db, body.email, body.password)
    _set_session(response, token, expires)
    return _login_payload(db, user_id, token)


def _login_payload(db: Session, user_id: UUID, token: str) -> dict[str, Any]:
    """The login response body for a signed-in user: profile, home space and every space they may enter."""
    with db.begin():
        user = db.get(UserRecord, user_id)
        user_view = _user_view(db, user)
    principal = Principal(id=user_view["username"], issuer=accounts.PASSWORD_PROVIDER)
    memberships = _memberships(db, principal)
    # The home space is the first enterprise the user joined. The client may pick another space with
    # switch-tenant, sending its id as X-Tenant-ID.
    # A remembered space (users.preferences.last_active_tenant_id) wins while the user is still a member.
    remembered = (user_view["preferences"] or {}).get("last_active_tenant_id")
    home = next((m for m in memberships if str(m["id"]) == remembered), None)
    if home is None:
        home = memberships[0] if memberships else None
    user_view["tenant_id"] = home["id"] if home else None
    return {
        "success": True,
        "user": user_view,
        "tenant": _tenant_info(home) if home else None,
        "active_tenant": _tenant_info(home) if home else None,
        "memberships": memberships,
        "token": token,
    }


@router.post("/dev-session")
def dev_session(response: Response, db: Session = Depends(get_database_session)):
    """Development mode only: sign in as the configured local account without a password.

    Issues a normal session for the account named by `[auth].dev_user_id`, so the web client stores and sends
    its token like any other login. Any other mode answers 404. The loopback guard limits it to this machine.
    """
    settings = auth_settings()
    if (settings.mode or "").casefold() != "development":
        raise NotFound("Not found")
    identity = development_identity(db, settings)  # runs and commits its own transaction
    with db.begin():
        token, expires = sessions.issue_session(db, identity.user_id, identity.id)
    _set_session(response, token, expires)
    return _login_payload(db, identity.user_id, token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, response: Response, db: Session = Depends(get_database_session)):
    """Revoke the token in use: the Bearer token if sent, otherwise the session cookie."""
    token = bearer_token(request) or request.cookies.get(SESSION_COOKIE)
    if request.cookies.get(SESSION_COOKIE) and bearer_token(request) is None:
        _require_csrf(request)
    sessions.revoke_session(db, token)
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.status_code = status.HTTP_204_NO_CONTENT


@router.get("/me")
def current_user(
    request: Request,
    principal: Principal = Depends(get_principal),
    tenant_id: UUID | None = Depends(get_tenant_header),
    db: Session = Depends(get_database_session),
):
    """The signed-in user, every space they belong to, and the space named by `X-Tenant-ID` when given."""
    with db.begin():
        user = resolve_user(db, principal)
        user_view = _user_view(db, user)
    current = None
    if tenant_id is not None:
        tenant, role = tenants.current_space(db, principal, tenant_id)
        current = _space_view(tenant, role)
    return {"success": True, "data": {"user": user_view, "tenant": current,
                                      "memberships": _memberships(db, principal)}}


@router.put("/me/preferences")
def update_my_preferences(body: PreferencesUpdate, request: Request, response: Response,
                          principal: Principal = Depends(get_principal),
                          db: Session = Depends(get_database_session)):
    """Save the user's preferences (currently the space to open at sign-in). Returns the stored preferences."""
    if request.cookies.get(SESSION_COOKIE) and bearer_token(request) is None:
        _require_csrf(request)
    patch = body.model_dump(exclude_unset=True)
    stored = preferences.update_preferences(db, principal, patch)
    return {"success": True, "data": {"preferences": stored}}


@router.post("/switch-tenant")
def switch_tenant(body: SwitchTenant, request: Request, principal: Principal = Depends(get_principal),
                  db: Session = Depends(get_database_session)):
    """Check that the caller may enter the space and return it. The client then sends it as `X-Tenant-ID`.

    The token does not change: the space is selected per request and membership is checked each time,
    so there is no separate session to revoke when the user switches.
    """
    tenant, role = tenants.current_space(db, principal, body.tenant_id)
    return {"success": True, "data": {"tenant": _space_view(tenant, role)}}


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
@router.post("/password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(body: PasswordChange, request: Request, response: Response,
                       principal: Principal = Depends(get_principal), db: Session = Depends(get_database_session)):
    """Change the password and revoke every session; the user signs in again with the new password."""
    if request.cookies.get(SESSION_COOKIE) and bearer_token(request) is None:
        _require_csrf(request)
    accounts.change_password(db, principal, body.current_password, body.new_password)
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.status_code = status.HTTP_204_NO_CONTENT


def _user_id_for(db: Session, principal: Principal) -> UUID:
    with db.begin():
        return resolve_user(db, principal).id


@router.get("/wecom/start")
def wecom_login_start(request: Request, db: Session = Depends(get_database_session)):
    directory = _directory(request)
    state = wecom.start_login(db)
    return RedirectResponse(directory.authorize_url(state), status_code=302)


@router.post("/wecom/bind/start")
def wecom_bind_start(request: Request, principal: Principal = Depends(get_principal),
                     db: Session = Depends(get_database_session)):
    _require_csrf(request)
    directory = _directory(request)
    state = wecom.start_binding(db, principal)
    return {"authorize_url": directory.authorize_url(state)}


@router.get("/wecom/callback")
def wecom_callback(request: Request, code: str = "", state: str = "",
                   db: Session = Depends(get_database_session)):
    """Single callback for both flows; the stored state decides whether this signs in or binds."""
    directory = _directory(request)
    corp_id = directory.corp_id
    purpose = wecom.state_purpose(db, state)
    if purpose == "bind":
        principal = _cookie_principal(request, db)
        if principal is None:
            return RedirectResponse("/personal/account?wecom=unauthenticated", status_code=303)
        user_id = _user_id_for(db, principal)
        try:
            wecom.bind_wecom(db, directory, code=code, state=state, corp_id=corp_id, expected_user_id=user_id)
        except (Unauthenticated, Forbidden, Conflict) as exc:
            return RedirectResponse(f"/personal/account?wecom={_error_key(exc)}", status_code=303)
        return RedirectResponse("/personal/account?wecom=bound", status_code=303)
    try:
        token, expires, _ = wecom.login_with_wecom(db, directory, code=code, state=state, corp_id=corp_id)
    except (Unauthenticated, Forbidden) as exc:
        return RedirectResponse(f"/login?error={_error_key(exc)}", status_code=303)
    response = RedirectResponse("/chat", status_code=303)
    _set_session(response, token, expires)
    return response


def _cookie_principal(request: Request, db: Session) -> Principal | None:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    try:
        principal, _ = sessions.resolve_session(db, token)
    except (Unauthenticated, Forbidden):
        return None
    return principal


def _error_key(exc: Exception) -> str:
    if isinstance(exc, Conflict):
        return "conflict"
    return "unbound" if isinstance(exc, Forbidden) and "尚未绑定" in str(exc) else "failed"
