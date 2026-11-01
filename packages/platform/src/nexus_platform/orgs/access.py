"""Activity rules for membership rows that come from an organization.

A membership with `source == "organization"` only takes effect while its user sits inside a node
bound to the same space. Leaving the bound subtree (or unbinding the space) does not delete the row;
it stops the row from granting anything, and returning restores it. Manual memberships are unaffected.

This module imports only persistence models and SQLAlchemy so that identity, authz, agents and
tenants can all depend on it without creating an import cycle.
"""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus_platform.persistence.models import MembershipRecord, OrgUnitRecord, TenantOrgBindingRecord, UserOrgUnitRecord

SOURCE_MANUAL = "manual"
SOURCE_ORGANIZATION = "organization"


def subtree_ids(session: Session, unit_id: UUID) -> set[UUID]:
    """Ids of a node and all its descendants, via a recursive CTE (works on SQLite and PostgreSQL)."""
    base = select(OrgUnitRecord.id).where(OrgUnitRecord.id == unit_id).cte("subtree", recursive=True)
    step = select(OrgUnitRecord.id).join(base, OrgUnitRecord.parent_id == base.c.id)
    return set(session.scalars(select(base.union_all(step).c.id)))


def bound_unit_ids(session: Session, tenant_id: UUID) -> set[UUID]:
    """Every node inside any subtree bound to the space."""
    bound: set[UUID] = set()
    for unit_id in session.scalars(select(TenantOrgBindingRecord.unit_id).where(
            TenantOrgBindingRecord.tenant_id == tenant_id)):
        bound |= subtree_ids(session, unit_id)
    return bound


def user_in_bound_subtree(session: Session, tenant_id: UUID, user_id: UUID) -> bool:
    """True when the user has a node inside a subtree bound to the space."""
    bound = bound_unit_ids(session, tenant_id)
    if not bound:
        return False
    return session.scalar(select(UserOrgUnitRecord.unit_id).where(
        UserOrgUnitRecord.user_id == user_id, UserOrgUnitRecord.unit_id.in_(bound)).limit(1)) is not None


def membership_is_active(session: Session, membership: MembershipRecord | None) -> bool:
    """A membership grants access when it is active and, for organization rows, its user is still bound."""
    if membership is None or membership.status != "active":
        return False
    if membership.source != SOURCE_ORGANIZATION:
        return True
    return user_in_bound_subtree(session, membership.tenant_id, membership.user_id)


def is_space_manager(session: Session, tenant_id: UUID, user_id: UUID) -> bool:
    """True for an active owner or admin whose membership is still effective.

    Owners and admins read every session, run and memory entry of their space. Organization-sourced
    people are never managers: their membership role is always `member`.
    """
    membership = session.get(MembershipRecord, (tenant_id, user_id))
    return membership is not None and membership.role in {"owner", "admin"} and membership_is_active(session, membership)


def organization_unit_for(session: Session, tenant_id: UUID, user_id: UUID) -> UUID | None:
    """The bound-subtree node a user came through, preferring the primary node. None when none applies."""
    bound = bound_unit_ids(session, tenant_id)
    if not bound:
        return None
    return session.scalar(
        select(UserOrgUnitRecord.unit_id).where(UserOrgUnitRecord.user_id == user_id, UserOrgUnitRecord.unit_id.in_(bound))
        .order_by(UserOrgUnitRecord.is_primary.desc(), UserOrgUnitRecord.unit_id).limit(1)
    )
