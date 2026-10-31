"""Login routes: password sign-in, WeCom QR sign-in and binding, sign-out and the current user.

Session cookies are HttpOnly and SameSite=Lax. Secure is on unless NEXUS_COOKIE_SECURE=0 (local
HTTP development only). Unsafe methods require the X-Nexus-Request header (see dependencies).
"""
from __future__ import annotations

import os
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus_core.platform import Principal
from nexus_platform.auth import accounts, sessions, wecom
from nexus_platform.errors import Conflict, Forbidden, Unauthenticated
from nexus_platform.persistence.models import UserIdentityRecord, UserRecord
from nexus_api.dependencies.platform import CSRF_HEADER, SESSION_COOKIE, get_database_session, get_principal
from nexus_api.http.wecom_directory import HttpWeComDirectory

router = APIRouter(prefix="/api/v1/auth", tags=["Authentication"])


class PasswordLogin(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=256)


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=10, max_length=256)


class CurrentUser(BaseModel):
    user_id: UUID
    display_name: str | None
    providers: list[str]


def _cookie_secure() -> bool:
    return os.getenv("NEXUS_COOKIE_SECURE", "1") != "0"


def _set_session(response: Response, token: str, expires: datetime) -> None:
    response.set_cookie(
        SESSION_COOKIE, token, httponly=True, samesite="lax", secure=_cookie_secure(),
        expires=expires, path="/",
    )


def _directory(request: Request):
    override = getattr(request.app.state, "wecom_directory", None)
    return override if override is not None else HttpWeComDirectory.from_environment()


def _require_csrf(request: Request) -> None:
    if request.headers.get(CSRF_HEADER) != "1":
        raise Forbidden("Missing request header for a session-authenticated write")


@router.post("/login", status_code=status.HTTP_204_NO_CONTENT)
def password_login(body: PasswordLogin, request: Request, response: Response,
                   db: Session = Depends(get_database_session)):
    _require_csrf(request)
    token, expires, _ = accounts.authenticate_password(db, body.username, body.password)
    _set_session(response, token, expires)
    response.status_code = status.HTTP_204_NO_CONTENT


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, response: Response, db: Session = Depends(get_database_session)):
    _require_csrf(request)
    sessions.revoke_session(db, request.cookies.get(SESSION_COOKIE))
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.status_code = status.HTTP_204_NO_CONTENT


@router.get("/me", response_model=CurrentUser)
def current_user(principal: Principal = Depends(get_principal), db: Session = Depends(get_database_session)):
    user_id = _user_id_for(db, principal)
    user = db.get(UserRecord, user_id)
    providers = list(db.scalars(select(UserIdentityRecord.provider).where(UserIdentityRecord.user_id == user_id)))
    return CurrentUser(user_id=user.id, display_name=user.display_name, providers=sorted(set(providers)))


def _user_id_for(db: Session, principal: Principal) -> UUID:
    from nexus_platform.identity.service import resolve_user

    with db.begin():
        return resolve_user(db, principal).id


@router.post("/password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(body: PasswordChange, request: Request, response: Response,
                    principal: Principal = Depends(get_principal), db: Session = Depends(get_database_session)):
    _require_csrf(request)
    accounts.change_password(db, principal, body.current_password, body.new_password)
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.status_code = status.HTTP_204_NO_CONTENT


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
            return RedirectResponse("/#account?wecom=unauthenticated", status_code=303)
        user_id = _user_id_for(db, principal)
        try:
            wecom.bind_wecom(db, directory, code=code, state=state, corp_id=corp_id, expected_user_id=user_id)
        except (Unauthenticated, Forbidden, Conflict) as exc:
            return RedirectResponse(f"/#account?wecom={_error_key(exc)}", status_code=303)
        return RedirectResponse("/#account?wecom=bound", status_code=303)
    try:
        token, expires, _ = wecom.login_with_wecom(db, directory, code=code, state=state, corp_id=corp_id)
    except (Unauthenticated, Forbidden) as exc:
        return RedirectResponse(f"/#login?error={_error_key(exc)}", status_code=303)
    response = RedirectResponse("/#chat", status_code=303)
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
