"""SQLAlchemy tenant mappings; domain-owned tables with their existing columns and constraints."""
from __future__ import annotations
from datetime import datetime
from uuid import UUID
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column
from ..base import Base


class TenantRecord(Base):
    __tablename__ = "tenants"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'archived')", name="ck_tenants_status"),
        CheckConstraint("kind IN ('personal', 'enterprise', 'system')", name="ck_tenants_kind"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    # Personal spaces have one member; enterprise spaces own an organization tree (openspec 2026-11-03).
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="enterprise", server_default="enterprise")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="active")
    # Recorded only (no directory sync yet). Binding a WeCom account is limited to this corp when set.
    wecom_corp_id: Mapped[str | None] = mapped_column(String(64))
    # Shown in the space settings. Empty means no description.
    description: Mapped[str | None] = mapped_column(String(500))
    # Enterprise code (企业编码) used at registration; unique when set. Personal spaces have none.
    code: Mapped[str | None] = mapped_column(String(32), unique=True)
    created_by: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MembershipRecord(Base):
    __tablename__ = "tenant_memberships"
    __table_args__ = (
        CheckConstraint("role IN ('owner', 'admin', 'contributor', 'viewer')", name="ck_membership_role"),
        CheckConstraint("status IN ('active', 'revoked')", name="ck_membership_status"),
        CheckConstraint("source IN ('manual', 'invitation', 'application')", name="ck_membership_source"),
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
    # How the membership was created: manual (admin-created), invitation (accepted), application (approved).
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="manual", server_default="manual")
