"""SQLAlchemy mappings for an enterprise's organization tree and members' positions in it.

A tree belongs to one enterprise (`tenant_id`): its root row points to itself through `root_id`.
Subsidiaries and departments are ordinary nodes below the root, so depth is not stored and not limited.
Organization audit rows are kept apart from `audit_records` because an organization may exist
without any bound space, and `audit_records.tenant_id` is required.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import JSON, Boolean, CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint, Index, String, UniqueConstraint, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base


class OrgUnitRecord(Base):
    """A node of an enterprise's organization tree (subsidiary or department). Each enterprise owns its tree."""

    __tablename__ = "org_units"
    __table_args__ = (
        # Sibling names are unique. Roots (parent_id NULL) are checked by the service because NULLs
        # never collide in a unique index.
        UniqueConstraint("parent_id", "name", name="uq_org_units_parent_name"),
        # Target of the composite foreign keys that keep memberships and requests inside one enterprise.
        UniqueConstraint("tenant_id", "id", name="uq_org_units_tenant_id"),
        Index("ix_org_units_root", "root_id"),
        Index("ix_org_units_tenant", "tenant_id"),
        CheckConstraint("status IN ('active', 'disabled')", name="ck_org_units_status"),
        CheckConstraint("source IN ('manual', 'wecom')", name="ck_org_units_source"),
        UniqueConstraint("tenant_id", "external_id", name="uq_org_units_external"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    root_id: Mapped[UUID] = mapped_column(ForeignKey("org_units.id", ondelete="RESTRICT"), nullable=False)
    parent_id: Mapped[UUID | None] = mapped_column(ForeignKey("org_units.id", ondelete="RESTRICT"))
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    # "manual": maintained by the enterprise. "wecom": read from the WeCom directory (openspec 2026-11-11 E3).
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="manual", server_default="manual")
    # The WeCom department id of a "wecom" node, unique within the enterprise; NULL for manual nodes.
    external_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class UserOrgUnitRecord(Base):
    """A member's position in one node of an enterprise's tree.

    The composite foreign keys guarantee that only a member of the enterprise can be placed in one of
    its nodes. A member has at most one primary node per enterprise. Positions never grant access.
    """

    __tablename__ = "user_org_units"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "user_id"], ["tenant_memberships.tenant_id", "tenant_memberships.user_id"],
            name="fk_user_org_units_membership", ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "unit_id"], ["org_units.tenant_id", "org_units.id"],
            name="fk_user_org_units_unit", ondelete="RESTRICT",
        ),
        # Partial unique index: at most one primary row per member per enterprise. SQLite stores booleans as 0/1.
        Index("uq_user_org_units_primary", "tenant_id", "user_id", unique=True,
              sqlite_where=text("is_primary = 1"), postgresql_where=text("is_primary")),
    )

    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    unit_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
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
