"""Password accounts: self-service registration, email login with lockout, password change and admin-created accounts.

A password account is a user with an identity `(provider='password', scope='', external_id=username)`,
a unique `users.email` and a `local_credentials` row. Registration creates the account together with its
first space: an enterprise whose owner is the registrant (openspec 2026-11-11-enterprise-saas decision 1; a
one-member enterprise is an ordinary enterprise). Name and enterprise code are optional and generated when empty.
Creating an account for someone else is a tenant administration action and adds the new user to that
tenant with the chosen role.
"""
from __future__ import annotations

import secrets

import re
from datetime import timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus_core.platform import Principal, TenantRole, new_id, utc_now
from nexus_platform.tenants.builtin_roles import ensure_builtin_roles
from nexus_platform.authz.audit import audit
from nexus_platform.authz.permissions import require_api_permission
from nexus_platform.auth.passwords import DUMMY_HASH, hash_password, validate_new_password, verify_password
from nexus_platform.auth.sessions import aware, issue_session, revoke_user_sessions
from nexus_platform.errors import Conflict, Forbidden, Unauthenticated
from nexus_platform.identity.service import require_membership, require_tenant, resolve_user
from nexus_platform.persistence.models import (
    LocalCredentialRecord,
    MembershipRecord,
    TenantRecord,
    UserIdentityRecord,
    UserRecord,
)

PASSWORD_PROVIDER = "password"
MAX_FAILED_ATTEMPTS = 5
LOCK_DURATION = timedelta(minutes=15)
_USERNAME = re.compile(r"^[a-z0-9][a-z0-9._-]{2,63}$")
_EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[^@\s]{2,}$")
_COMPANY_CODE = re.compile(r"^[a-z0-9][a-z0-9_-]{2,31}$")
#: Accepted for compatibility with clients that still send ``space_kind``; every registration creates an enterprise.
SPACE_KINDS = frozenset({"personal", "enterprise"})
GENERIC_FAILURE = "邮箱或密码错误"


def normalize_username(value: str) -> str:
    username = value.strip().lower()
    if not _USERNAME.fullmatch(username):
        raise ValueError("Username must be 3-64 characters: lowercase letters, digits, dot, dash or underscore")
    return username


def normalize_email(value: str) -> str:
    address = (value or "").strip().lower()
    if len(address) > 255 or not _EMAIL.fullmatch(address):
        raise ValueError("Email address is not valid")
    return address


def normalize_company_code(value: str) -> str:
    code = (value or "").strip().lower()
    if not _COMPANY_CODE.fullmatch(code):
        raise ValueError("Company code must be 3-32 characters: lowercase letters, digits, dash or underscore")
    return code


def _password_identity_taken(session: Session, username: str) -> bool:
    return session.scalar(select(UserIdentityRecord.id).where(
        UserIdentityRecord.provider == PASSWORD_PROVIDER,
        UserIdentityRecord.scope == "",
        UserIdentityRecord.external_id == username,
    )) is not None


def register(
    session: Session, *, username: str, email: str, password: str, space_kind: str = "enterprise",
    space_name: str = "", company_code: str = "", display_name: str = "", allow_registration: bool = True,
) -> tuple[UserRecord, TenantRecord]:
    """Self-service sign-up. Creates the account and its first enterprise, owned by the registrant.

    ``space_kind`` is ignored apart from validation: personal spaces no longer exist. ``space_name`` defaults to
    "{display name}的企业" and ``company_code`` to a generated unique code. When ``allow_registration`` is false
    (``[auth].registration_enabled``), the call is refused before any write.
    """
    if not allow_registration:
        raise Forbidden("注册已关闭，请联系管理员")
    username = normalize_username(username)
    address = normalize_email(email)
    validate_new_password(password)
    if space_kind not in SPACE_KINDS:
        raise ValueError("Space kind must be personal or enterprise")
    code: str | None = normalize_company_code(company_code) if company_code.strip() else None
    now = utc_now()
    with session.begin():
        if _password_identity_taken(session, username):
            raise Conflict("用户名已被占用")
        if session.scalar(select(UserRecord.id).where(UserRecord.email == address)) is not None:
            raise Conflict("邮箱已被注册")
        if code is not None and session.scalar(select(TenantRecord.id).where(TenantRecord.code == code)) is not None:
            raise Conflict("企业编码已被占用")
        while code is None:
            candidate = f"e{secrets.token_hex(5)}"
            if session.scalar(select(TenantRecord.id).where(TenantRecord.code == candidate)) is None:
                code = candidate
        user = UserRecord(id=new_id(), display_name=display_name.strip() or username, email=address,
                          status="active", must_change_password=False, created_at=now)
        session.add(user)
        session.flush()
        session.add(UserIdentityRecord(
            id=new_id(), user_id=user.id, provider=PASSWORD_PROVIDER, scope="", external_id=username,
            verified_at=now, created_at=now,
        ))
        session.add(LocalCredentialRecord(
            user_id=user.id, password_hash=hash_password(password), failed_attempts=0, updated_at=now,
        ))
        name = space_name.strip() or f"{user.display_name}的企业"
        space = TenantRecord(id=new_id(), name=name[:160], kind="enterprise", code=code, status="active",
                             created_by=user.id, created_at=now, updated_at=now)
        session.add(space)
        session.flush()
        ensure_builtin_roles(session, space.id)
        session.add(MembershipRecord(
            tenant_id=space.id, user_id=user.id, role=TenantRole.OWNER.value, status="active", joined_at=now,
        ))
        audit(session, space.id, user.id, "tenant.created", "tenant", str(space.id), {"kind": "enterprise"})
    return user, space


def create_password_account(
    session: Session, principal: Principal, tenant_id: UUID, *,
    username: str, email: str, display_name: str, password: str, role: TenantRole,
) -> UserRecord:
    """Create a password account for someone else and add it to the tenant. The caller needs `members:manage`.

    The account signs in with `email`, which must not be registered yet. The initial password is
    temporary: `must_change_password` is set, so the user changes it on first sign-in.
    """
    if role == TenantRole.OWNER:
        raise Forbidden("Owner accounts cannot be created this way")
    username = normalize_username(username)
    address = normalize_email(email)
    validate_new_password(password)
    display = display_name.strip() or username
    now = utc_now()
    with session.begin():
        actor = resolve_user(session, principal)
        require_tenant(session, tenant_id)
        require_membership(session, tenant_id, actor.id)
        require_api_permission(session, tenant_id, actor.id, "members:manage")
        if _password_identity_taken(session, username):
            raise Conflict("Username is already taken")
        if session.scalar(select(UserRecord.id).where(UserRecord.email == address)) is not None:
            raise Conflict("Email is already registered")
        user = UserRecord(id=new_id(), display_name=display, email=address, status="active",
                          must_change_password=True, created_at=now)
        session.add(user)
        session.flush()
        session.add(UserIdentityRecord(
            id=new_id(), user_id=user.id, provider=PASSWORD_PROVIDER, scope="", external_id=username,
            verified_at=now, created_at=now,
        ))
        session.add(LocalCredentialRecord(
            user_id=user.id, password_hash=hash_password(password), failed_attempts=0, updated_at=now,
        ))
        session.add(MembershipRecord(
            tenant_id=tenant_id, user_id=user.id, role=role.value, status="active", joined_at=now,
        ))
        audit(session, tenant_id, actor.id, "tenant.account_created", "user", str(user.id),
              {"role": role.value})
    return user


def authenticate_email(session: Session, email: str, password: str) -> tuple[str, object, UUID]:
    """Sign in with email and password. Returns (raw token, expiry, user id).

    Unknown emails, wrong passwords and disabled accounts share one generic message; a lock says the
    account is temporarily locked. Failure counters are committed before the error is raised, so the
    lock survives the failed request.
    """
    try:
        address = normalize_email(email)
    except ValueError:
        verify_password(password[:256], DUMMY_HASH)
        raise Unauthenticated(GENERIC_FAILURE) from None
    now = utc_now()
    error: str | None = None
    with session.begin():
        user = session.scalar(select(UserRecord).where(UserRecord.email == address))
        identity = session.scalar(select(UserIdentityRecord).where(
            UserIdentityRecord.user_id == user.id,
            UserIdentityRecord.provider == PASSWORD_PROVIDER,
            UserIdentityRecord.scope == "",
        )) if user is not None else None
        credential = session.get(LocalCredentialRecord, user.id) if user is not None else None
        if user is None or identity is None or credential is None or user.status != "active":
            verify_password(password[:256], DUMMY_HASH)
            error = GENERIC_FAILURE
        elif credential.locked_until and aware(credential.locked_until) > now:
            error = "账号已暂时锁定，请稍后再试"
        elif not verify_password(password[:256], credential.password_hash):
            credential.failed_attempts += 1
            if credential.failed_attempts >= MAX_FAILED_ATTEMPTS:
                credential.locked_until = now + LOCK_DURATION
                credential.failed_attempts = 0
            error = GENERIC_FAILURE
        else:
            credential.failed_attempts = 0
            credential.locked_until = None
            token, expires = issue_session(session, user.id, identity.id)
    if error is not None:
        raise Unauthenticated(error)
    return token, expires, user.id


def change_password(session: Session, principal: Principal, current: str, new: str) -> None:
    """Change the caller's password after checking the current one; all sessions are revoked."""
    validate_new_password(new)
    with session.begin():
        user = resolve_user(session, principal)
        credential = session.get(LocalCredentialRecord, user.id)
        if credential is None or not verify_password(current, credential.password_hash):
            raise Unauthenticated("当前密码不正确")
        credential.password_hash = hash_password(new)
        credential.failed_attempts = 0
        credential.locked_until = None
        credential.updated_at = utc_now()
        user.must_change_password = False
        revoke_user_sessions(session, user.id)


def create_owner_account(session: Session, *, tenant_name: str, username: str, email: str, display_name: str,
                         password: str) -> UUID:
    """Operator bootstrap: create an enterprise space and its first owner with a password account.

    Only the operator CLI calls this; there is no HTTP path to create owners. The email is required
    because sign-in uses it. Returns the space id.
    """
    from nexus_platform.tenants.service import create_tenant

    username = normalize_username(username)
    address = normalize_email(email)
    validate_new_password(password)
    if not tenant_name.strip():
        raise ValueError("Tenant name must not be empty")
    now = utc_now()
    with session.begin():
        if _password_identity_taken(session, username):
            raise Conflict("Username is already taken")
        if session.scalar(select(UserRecord.id).where(UserRecord.email == address)) is not None:
            raise Conflict("Email is already registered")
        user = UserRecord(id=new_id(), display_name=display_name.strip() or username, email=address,
                          status="active", must_change_password=False, created_at=now)
        session.add(user)
        session.flush()
        identity = UserIdentityRecord(
            id=new_id(), user_id=user.id, provider=PASSWORD_PROVIDER, scope="", external_id=username,
            verified_at=now, created_at=now,
        )
        session.add(identity)
        session.add(LocalCredentialRecord(
            user_id=user.id, password_hash=hash_password(password), failed_attempts=0, updated_at=now,
        ))
    tenant = create_tenant(session, Principal(id=username, issuer=PASSWORD_PROVIDER), tenant_name)
    return tenant.id
