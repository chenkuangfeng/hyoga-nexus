"""Helpers for an enterprise's organization tree and space-manager checks.

A node's position is information only: it never grants access to a space, a resource or a shared
space (openspec 2026-11-03-enterprise-personal-spaces, decision 7–8). Access is decided by membership,
roles and sharing rules alone.
"""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus_platform.persistence.models import MembershipRecord, OrgUnitRecord


def subtree_ids(session: Session, unit_id: UUID) -> set[UUID]:
    """The node and every node below it, across all depths."""
    base = select(OrgUnitRecord.id).where(OrgUnitRecord.id == unit_id).cte("subtree", recursive=True)
    child = select(OrgUnitRecord.id).join(base, OrgUnitRecord.parent_id == base.c.id)
    return set(session.scalars(select(base.union_all(child).c.id)))


def membership_is_active(session: Session, membership: MembershipRecord | None) -> bool:
    """A membership grants access only while it is active. The session argument is kept for callers."""
    del session
    return membership is not None and membership.status == "active"


def is_space_manager(session: Session, tenant_id: UUID, user_id: UUID) -> bool:
    """Owners and admins of a space manage its members, roles and organization tree."""
    membership = session.get(MembershipRecord, (tenant_id, user_id))
    return membership_is_active(session, membership) and membership.role in {"owner", "admin"}
