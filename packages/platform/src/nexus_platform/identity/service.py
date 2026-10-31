"""Resolve an authenticated principal to the internal user it is linked to."""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus_core.platform import Principal, new_id, utc_now
from nexus_platform.errors import Forbidden, NotFound
from nexus_platform.persistence.models import MembershipRecord, TenantRecord, UserIdentityRecord, UserRecord


def resolve_user(session: Session, principal: Principal) -> UserRecord:
    """Return the user linked to (provider, external id), creating user and identity on first sight.

    `principal.issuer` is the provider name; scope is empty until a provider needs tenant-scoped IDs.
    """
    identity = session.scalar(
        select(UserIdentityRecord).where(
            UserIdentityRecord.provider == principal.issuer,
            UserIdentityRecord.scope == "",
            UserIdentityRecord.external_id == principal.id,
        )
    )
    if identity is not None:
        user = session.get(UserRecord, identity.user_id)
        if user.status != "active":
            raise Forbidden("The authenticated user is disabled")
        return user
    now = utc_now()
    user = UserRecord(id=new_id(), display_name=principal.id, status="active", created_at=now)
    session.add(user)
    session.flush()  # the identity row references the user; insert the user first
    session.add(
        UserIdentityRecord(
            id=new_id(), user_id=user.id, provider=principal.issuer, scope="", external_id=principal.id,
            verified_at=now, created_at=now,
        )
    )
    session.flush()
    return user


def principal_for_user(session: Session, user_id: UUID) -> Principal:
    """Return a stable external principal that resolves back to `user_id`.

    Runs store the internal user id; authorization calls that re-resolve identity need one of the
    user's linked identities. The earliest identity is chosen so the choice is deterministic.
    """
    identity = session.scalar(
        select(UserIdentityRecord)
        .where(UserIdentityRecord.user_id == user_id)
        .order_by(UserIdentityRecord.created_at, UserIdentityRecord.id)
        .limit(1)
    )
    if identity is None:
        raise NotFound("User identity not found")
    return Principal(id=identity.external_id, issuer=identity.provider)


def require_membership(
    session: Session, tenant_id: UUID, user_id: UUID, *, roles: set[str] | None = None
) -> MembershipRecord:
    membership = session.get(MembershipRecord, (tenant_id, user_id))
    if membership is None or membership.status != "active":
        raise NotFound("Tenant not found")
    if roles is not None and membership.role not in roles:
        raise Forbidden("Your tenant role does not allow this action")
    return membership


def require_tenant(session: Session, tenant_id: UUID) -> TenantRecord:
    tenant = session.get(TenantRecord, tenant_id)
    if tenant is None or tenant.status != "active":
        raise NotFound("Tenant not found")
    return tenant
