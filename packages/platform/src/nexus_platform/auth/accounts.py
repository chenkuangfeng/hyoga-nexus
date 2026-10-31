"""Password accounts: admin-created accounts, password login with lockout, and self-service password change.

A password account is a user with an identity `(provider='password', scope='', external_id=username)`
and a `local_credentials` row. Creating an account is a tenant administration action and also
adds the new user to that tenant with the chosen role.
"""
from __future__ import annotations

import re
from datetime import timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus_core.platform import Principal, TenantRole, new_id, utc_now
from nexus_platform.authz.audit import audit
from nexus_platform.authz.permissions import require_api_permission
from nexus_platform.auth.passwords import DUMMY_HASH, hash_password, validate_new_password, verify_password
from nexus_platform.auth.sessions import aware, issue_session, revoke_user_sessions
from nexus_platform.errors import Conflict, Forbidden, Unauthenticated
from nexus_platform.identity.service import require_membership, require_tenant, resolve_user
from nexus_platform.persistence.models import (
    LocalCredentialRecord,
    MembershipRecord,
    UserIdentityRecord,
    UserRecord,
)

PASSWORD_PROVIDER = "password"
MAX_FAILED_ATTEMPTS = 5
LOCK_DURATION = timedelta(minutes=15)
_USERNAME = re.compile(r"^[a-z0-9][a-z0-9._-]{2,63}$")
GENERIC_FAILURE = "用户名或密码错误"


def normalize_username(value: str) -> str:
    username = value.strip().lower()
    if not _USERNAME.fullmatch(username):
        raise ValueError("Username must be 3-64 characters: lowercase letters, digits, dot, dash or underscore")
    return username


def create_password_account(
    session: Session, principal: Principal, tenant_id: UUID, *,
    username: str, display_name: str, password: str, role: TenantRole,
) -> UserRecord:
    """Create a password account and add it to the tenant. The caller needs `members:manage`."""
    if role == TenantRole.OWNER:
        raise Forbidden("Owner accounts cannot be created this way")
    username = normalize_username(username)
    validate_new_password(password)
    display = display_name.strip() or username
    now = utc_now()
    with session.begin():
        actor = resolve_user(session, principal)
        require_tenant(session, tenant_id)
        require_membership(session, tenant_id, actor.id)
        require_api_permission(session, tenant_id, actor.id, "members:manage")
        if session.scalar(select(UserIdentityRecord.id).where(
            UserIdentityRecord.provider == PASSWORD_PROVIDER,
            UserIdentityRecord.scope == "",
            UserIdentityRecord.external_id == username,
        )) is not None:
            raise Conflict("Username is already taken")
        user = UserRecord(id=new_id(), display_name=display, status="active", created_at=now)
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


def authenticate_password(session: Session, username: str, password: str) -> tuple[str, object, UUID]:
    """Verify a password and open a session. Returns (raw token, expiry, user id).

    Unknown users, wrong passwords and disabled accounts share one generic message; a lock says
    the account is temporarily locked. Failure counters are committed before the error is raised,
    so the lock survives the failed request.
    """
    try:
        name = normalize_username(username)
    except ValueError:
        verify_password(password[:256], DUMMY_HASH)
        raise Unauthenticated(GENERIC_FAILURE) from None
    now = utc_now()
    error: str | None = None
    with session.begin():
        identity = session.scalar(select(UserIdentityRecord).where(
            UserIdentityRecord.provider == PASSWORD_PROVIDER,
            UserIdentityRecord.scope == "",
            UserIdentityRecord.external_id == name,
        ))
        credential = session.get(LocalCredentialRecord, identity.user_id) if identity else None
        user = session.get(UserRecord, identity.user_id) if identity else None
        if identity is None or credential is None or user is None or user.status != "active":
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
        revoke_user_sessions(session, user.id)


def create_owner_account(session: Session, *, tenant_name: str, username: str, display_name: str,
                         password: str) -> UUID:
    """Operator bootstrap: create a tenant and its first owner with a password account.

    Only the operator CLI calls this; there is no HTTP path to create owners. Returns the tenant id.
    """
    from nexus_platform.tenants.service import create_tenant

    username = normalize_username(username)
    validate_new_password(password)
    if not tenant_name.strip():
        raise ValueError("Tenant name must not be empty")
    now = utc_now()
    with session.begin():
        if session.scalar(select(UserIdentityRecord.id).where(
            UserIdentityRecord.provider == PASSWORD_PROVIDER,
            UserIdentityRecord.scope == "",
            UserIdentityRecord.external_id == username,
        )) is not None:
            raise Conflict("Username is already taken")
        user = UserRecord(id=new_id(), display_name=display_name.strip() or username, status="active", created_at=now)
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
