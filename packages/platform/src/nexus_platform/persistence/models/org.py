"""SQLAlchemy mappings for the organization tree, person-to-node membership and space bindings.

A tree is one organization (group): its root row points to itself through `root_id`. Subsidiaries
and departments are ordinary nodes below the root, so depth is not stored and not limited.
Organization audit rows are kept apart from `audit_records` because an organization may exist
without any bound space, and `audit_records.tenant_id` is required.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import JSON, Boolean, CheckConstraint, DateTime, ForeignKey, Index, String, UniqueConstraint, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base


class OrgUnitRecord(Base):
    __tablename__ = "org_units"
    __table_args__ = (
        # Sibling names are unique. Roots (parent_id NULL) are checked by the service because NULLs
        # never collide in a unique index.
        UniqueConstraint("parent_id", "name", name="uq_org_units_parent_name"),
        Index("ix_org_units_root", "root_id"),
        CheckConstraint("status IN ('active', 'disabled')", name="ck_org_units_status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    root_id: Mapped[UUID] = mapped_column(ForeignKey("org_units.id", ondelete="RESTRICT"), nullable=False)
    parent_id: Mapped[UUID | None] = mapped_column(ForeignKey("org_units.id", ondelete="RESTRICT"))
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class UserOrgUnitRecord(Base):
    """A person's membership in one node. Each user has at most one primary node."""

    __tablename__ = "user_org_units"
    __table_args__ = (
        # Partial unique index: at most one primary row per user. SQLite stores booleans as 0/1.
        Index("uq_user_org_units_primary", "user_id", unique=True,
              sqlite_where=text("is_primary = 1"), postgresql_where=text("is_primary")),
    )

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    unit_id: Mapped[UUID] = mapped_column(ForeignKey("org_units.id", ondelete="RESTRICT"), primary_key=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class TenantOrgBindingRecord(Base):
    """A space bound to one organization node; the node's whole subtree is visible in the space."""

    __tablename__ = "tenant_org_bindings"
    __table_args__ = (Index("ix_tenant_org_bindings_unit", "unit_id"),)

    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True)
    unit_id: Mapped[UUID] = mapped_column(ForeignKey("org_units.id", ondelete="RESTRICT"), primary_key=True)
    created_by: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class OrgAuditRecord(Base):
    """Append-only audit for organization changes. `root_id` is not a foreign key so history outlives a tree."""

    __tablename__ = "org_audit_records"
    __table_args__ = (Index("ix_org_audit_root_time", "root_id", "created_at"),)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    root_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    actor_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    target_type: Mapped[str] = mapped_column(String(80), nullable=False)
    target_id: Mapped[str] = mapped_column(String(255), nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
