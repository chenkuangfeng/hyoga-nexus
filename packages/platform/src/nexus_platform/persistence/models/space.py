"""SQLAlchemy mappings for space joins and shared spaces (openspec 2026-11-03-enterprise-personal-spaces).

- `space_join_requests`: a user applies to join an enterprise, or an enterprise invites a user. One pending
  request per person per enterprise. Approval creates a membership with the requested role and position.
- `shared_spaces`: WeKnora's organization, named shared space here. Spaces (tenants) join it, not people.
  Sharing resources into it is decided by the sharing space's role and the shared space's role.
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint, Index, Integer, String, Text, UniqueConstraint, Uuid, false, text
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base


class SpaceJoinRequestRecord(Base):
    __tablename__ = "space_join_requests"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "unit_id"], ["org_units.tenant_id", "org_units.id"],
            name="fk_space_join_requests_unit", ondelete="RESTRICT",
        ),
        CheckConstraint("direction IN ('application', 'invitation')", name="ck_space_join_requests_direction"),
        CheckConstraint("status IN ('pending', 'approved', 'rejected', 'withdrawn')", name="ck_space_join_requests_status"),
        CheckConstraint("role IN ('admin', 'contributor', 'viewer')", name="ck_space_join_requests_role"),
        Index("uq_space_join_requests_pending", "tenant_id", "user_id", unique=True,
              sqlite_where=text("status = 'pending'"), postgresql_where=text("status = 'pending'")),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    direction: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    # Owner is never requested or granted here; it is assigned only at creation of the space.
    role: Mapped[str] = mapped_column(String(16), nullable=False, default="contributor")
    unit_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    message: Mapped[str | None] = mapped_column(Text)
    reject_reason: Mapped[str | None] = mapped_column(Text)
    # Set on rejection: the person may apply again only after this time.
    cooldown_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    reviewed_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SharedSpaceRecord(Base):
    """A shared space (WeKnora organization). `owner_tenant_id` is the space that created it."""

    __tablename__ = "shared_spaces"
    __table_args__ = (
        UniqueConstraint("invite_code", name="uq_shared_spaces_invite_code"),
        Index("ix_shared_spaces_owner_tenant", "owner_tenant_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    owner_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    owner_tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False)
    invite_code: Mapped[str | None] = mapped_column(String(32))
    invite_code_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    invite_code_validity_days: Mapped[int] = mapped_column(Integer, nullable=False, default=7, server_default="7")
    require_approval: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    searchable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    member_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=50, server_default="50")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SharedSpaceTenantMemberRecord(Base):
    """A space that takes part in a shared space, with its role there (admin, editor or viewer)."""

    __tablename__ = "shared_space_tenant_members"
    __table_args__ = (
        CheckConstraint("role IN ('admin', 'editor', 'viewer')", name="ck_shared_space_members_role"),
        Index("ix_shared_space_members_tenant", "tenant_id"),
    )

    shared_space_id: Mapped[UUID] = mapped_column(
        ForeignKey("shared_spaces.id", ondelete="CASCADE"), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True)
    role: Mapped[str] = mapped_column(String(16), nullable=False, default="viewer", server_default="viewer")
    representative_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SharedSpaceJoinRequestRecord(Base):
    """A join request (`join`) or a role upgrade (`upgrade`) from a space to a shared space."""

    __tablename__ = "shared_space_join_requests"
    __table_args__ = (
        CheckConstraint("request_type IN ('join', 'upgrade')", name="ck_shared_space_join_type"),
        CheckConstraint("requested_role IN ('admin', 'editor', 'viewer')", name="ck_shared_space_join_role"),
        CheckConstraint("status IN ('pending', 'approved', 'rejected')", name="ck_shared_space_join_status"),
        Index("uq_shared_space_join_pending", "shared_space_id", "tenant_id", "request_type", unique=True,
              sqlite_where=text("status = 'pending'"), postgresql_where=text("status = 'pending'")),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    shared_space_id: Mapped[UUID] = mapped_column(ForeignKey("shared_spaces.id", ondelete="CASCADE"), nullable=False)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    request_type: Mapped[str] = mapped_column(String(16), nullable=False, default="join", server_default="join")
    prev_role: Mapped[str | None] = mapped_column(String(16))
    requested_role: Mapped[str] = mapped_column(String(16), nullable=False, default="viewer", server_default="viewer")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending", server_default="pending")
    message: Mapped[str | None] = mapped_column(Text)
    reviewed_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    review_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
