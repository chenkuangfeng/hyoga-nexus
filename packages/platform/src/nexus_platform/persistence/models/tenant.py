"""SQLAlchemy tenant mappings; domain-owned tables with their existing columns and constraints."""
from __future__ import annotations
from datetime import datetime
from uuid import UUID
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column
from ..base import Base


class TenantRecord(Base):
    __tablename__ = "tenants"
    __table_args__ = (CheckConstraint("status IN ('active', 'archived')", name="ck_tenants_status"),)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="active")
    created_by: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MembershipRecord(Base):
    __tablename__ = "tenant_memberships"
    __table_args__ = (
        CheckConstraint("role IN ('owner', 'admin', 'member')", name="ck_membership_role"),
        CheckConstraint("status IN ('active', 'revoked')", name="ck_membership_status"),
        CheckConstraint("source IN ('manual', 'organization')", name="ck_membership_source"),
        Index("ix_memberships_user_status", "user_id", "status"),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # "manual": joined directly. "organization": created when a role was given to a bound-subtree person;
    # it grants access only while the user stays inside a bound subtree (see orgs/access.py).
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="manual", server_default="manual")
