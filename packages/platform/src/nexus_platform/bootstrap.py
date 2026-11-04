"""Idempotent bootstrap of the default enterprise space and its owner account.

The API calls ensure_default_enterprise() when it starts. Each record is created only when it is
missing, so restarts change nothing once the space, account and membership exist:

- the account is looked up by email (sign-in uses email) and created with the password identity;
- the space is looked up by name among active enterprise spaces and created with that account as owner;
- the account's owner membership is added when missing, and reactivated when it was revoked.

The default password is deliberately exempt from the length policy because it is a fixed
development credential. Change it (or disable this bootstrap) before using the deployment for real data.
"""
from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus_core.platform import TenantRole, new_id, utc_now
from nexus_platform.auth.accounts import PASSWORD_PROVIDER
from nexus_platform.auth.passwords import hash_password_unchecked
from nexus_platform.authz.audit import audit
from nexus_platform.persistence.models import (
    LocalCredentialRecord,
    MembershipRecord,
    TenantRecord,
    UserIdentityRecord,
    UserRecord,
)

DEFAULT_SPACE_NAME = "hyoga"
DEFAULT_OWNER_EMAIL = "9600543@qq.com"
DEFAULT_OWNER_USERNAME = "9600543"
DEFAULT_OWNER_DISPLAY_NAME = "9600543"
DEFAULT_OWNER_PASSWORD = "123456"


@dataclass(frozen=True)
class BootstrapResult:
    """What the bootstrap found or created; every flag is False when the record already existed."""

    space_id: UUID
    owner_id: UUID
    created_owner: bool
    created_space: bool
    granted_membership: bool


def ensure_default_enterprise(session: Session) -> BootstrapResult:
    """Create the default enterprise space and owner account if they are missing; return what happened.

    Raises RuntimeError when the default username already belongs to a different email address.
    """
    now = utc_now()
    with session.begin():
        user = session.scalar(select(UserRecord).where(UserRecord.email == DEFAULT_OWNER_EMAIL))
        created_owner = False
        if user is None:
            username_taken = session.scalar(select(UserIdentityRecord.id).where(
                UserIdentityRecord.provider == PASSWORD_PROVIDER,
                UserIdentityRecord.scope == "",
                UserIdentityRecord.external_id == DEFAULT_OWNER_USERNAME,
            )) is not None
            if username_taken:
                raise RuntimeError(f"Bootstrap username {DEFAULT_OWNER_USERNAME!r} belongs to another account")
            user = UserRecord(
                id=new_id(), display_name=DEFAULT_OWNER_DISPLAY_NAME, email=DEFAULT_OWNER_EMAIL,
                status="active", must_change_password=False, created_at=now,
            )
            session.add(user)
            session.flush()
            session.add(UserIdentityRecord(
                id=new_id(), user_id=user.id, provider=PASSWORD_PROVIDER, scope="",
                external_id=DEFAULT_OWNER_USERNAME, verified_at=now, created_at=now,
            ))
            session.add(LocalCredentialRecord(
                user_id=user.id, password_hash=hash_password_unchecked(DEFAULT_OWNER_PASSWORD),
                failed_attempts=0, updated_at=now,
            ))
            created_owner = True

        space = session.scalar(select(TenantRecord).where(
            TenantRecord.name == DEFAULT_SPACE_NAME,
            TenantRecord.kind == "enterprise",
            TenantRecord.status == "active",
        ).limit(1))
        created_space = False
        if space is None:
            space = TenantRecord(
                id=new_id(), name=DEFAULT_SPACE_NAME, kind="enterprise", status="active",
                created_by=user.id, created_at=now, updated_at=now,
            )
            session.add(space)
            session.flush()
            audit(session, space.id, user.id, "tenant.created", "tenant", str(space.id), {"kind": "enterprise"})
            created_space = True

        membership = session.get(MembershipRecord, (space.id, user.id))
        granted_membership = False
        if membership is None:
            session.add(MembershipRecord(
                tenant_id=space.id, user_id=user.id, role=TenantRole.OWNER.value,
                status="active", joined_at=now,
            ))
            granted_membership = True
        elif membership.status != "active":
            membership.status = "active"
            membership.role = TenantRole.OWNER.value
            membership.revoked_at = None
            granted_membership = True
        if granted_membership:
            audit(session, space.id, user.id, "tenant.member_added", "user", str(user.id), {"role": "owner"})

    return BootstrapResult(
        space_id=space.id, owner_id=user.id, created_owner=created_owner,
        created_space=created_space, granted_membership=granted_membership,
    )
