"""SQLAlchemy tenant mappings; domain-owned tables with their existing columns and constraints."""
from __future__ import annotations
from datetime import datetime
from uuid import UUID
from sqlalchemy import JSON, Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Uuid, false, true
from sqlalchemy.orm import Mapped, mapped_column
from ..base import Base


class TenantRecord(Base):
    __tablename__ = "tenants"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'archived')", name="ck_tenants_status"),
        CheckConstraint("kind IN ('enterprise', 'system')", name="ck_tenants_kind"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    # Every tenant is an enterprise (openspec 2026-11-11-enterprise-saas): a one-member enterprise is an ordinary
    # enterprise. ``system`` is the reserved tenant that owns builtin skills and tools.
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="enterprise", server_default="enterprise")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="active")
    # Recorded only (no directory sync yet). Binding a WeCom account is limited to this corp when set.
    wecom_corp_id: Mapped[str | None] = mapped_column(String(64))
    # Shown in the space settings. Empty means no description.
    description: Mapped[str | None] = mapped_column(String(500))
    # Enterprise code (企业编码), unique; generated at registration when the registrant leaves it empty.
    code: Mapped[str | None] = mapped_column(String(32), unique=True)
    created_by: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MembershipRecord(Base):
    __tablename__ = "tenant_memberships"
    __table_args__ = (
        CheckConstraint("role IN ('owner', 'admin', 'contributor', 'viewer')", name="ck_membership_role"),
        CheckConstraint("status IN ('active', 'suspended', 'revoked')", name="ck_membership_status"),
        CheckConstraint("source IN ('manual', 'invitation', 'application', 'wecom')", name="ck_membership_source"),
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
    suspended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # How the membership was created: manual (admin-created), invitation (accepted), application (approved).
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="manual", server_default="manual")


class EnterprisePolicyRecord(Base):
    """Per-enterprise policy (openspec 2026-11-11-enterprise-saas decision 4). It only tightens platform checks.

    A missing row means the defaults below; rows are written when an administrator first saves the policy.
    """
    __tablename__ = "enterprise_policies"
    __table_args__ = (
        CheckConstraint("self_build_agents IN ('all', 'org_units', 'none')", name="ck_enterprise_policies_self_build"),
        CheckConstraint("personal_wecom_channels IN ('review', 'open', 'disabled')",
                        name="ck_enterprise_policies_wecom_channels"),
    )

    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True)
    #: Who may create personal agents: everyone (``all``), members of the listed departments, or nobody.
    self_build_agents: Mapped[str] = mapped_column(String(16), nullable=False, default="all", server_default="all")
    self_build_org_unit_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    #: Whether members may use their own model providers and keys inside the enterprise.
    personal_models: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    #: Whether agents and bases may be shared into shared spaces that include other enterprises.
    external_sharing: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    #: WeCom bots on personal agents: need review, are open, or are disabled (used by IM channels).
    personal_wecom_channels: Mapped[str] = mapped_column(String(16), nullable=False, default="review",
                                                         server_default="review")
    #: Whether personal agents may bind the creator's own WeChat or QQ (used by IM channels).
    personal_external_channels: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True,
                                                             server_default=true())
    #: Days to keep sessions and run events; NULL keeps them.
    retention_days: Mapped[int | None] = mapped_column(Integer)
    updated_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
