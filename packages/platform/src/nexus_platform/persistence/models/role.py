"""Tenant roles: named bundles of menu and backend-API grants assigned to tenant members.

A member's effective access is the union of the grants of every role they hold. Owner and admin
memberships keep their built-in full access; custom roles only add permissions. Composite keys
tie each assignment to the same tenant as its role and membership, so cross-tenant rows are
rejected by the database.
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, ForeignKeyConstraint, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base


class TenantRoleRecord(Base):
    __tablename__ = "tenant_roles"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_tenant_roles_tenant_name"),
        UniqueConstraint("id", "tenant_id", name="uq_tenant_roles_id_tenant"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class TenantRoleMenuGrantRecord(Base):
    __tablename__ = "tenant_role_menu_grants"

    role_id: Mapped[UUID] = mapped_column(ForeignKey("tenant_roles.id", ondelete="CASCADE"), primary_key=True)
    menu: Mapped[str] = mapped_column(String(64), primary_key=True)


class TenantRoleApiGrantRecord(Base):
    __tablename__ = "tenant_role_api_grants"

    role_id: Mapped[UUID] = mapped_column(ForeignKey("tenant_roles.id", ondelete="CASCADE"), primary_key=True)
    permission: Mapped[str] = mapped_column(String(64), primary_key=True)


class TenantUserRoleRecord(Base):
    __tablename__ = "tenant_user_roles"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            ["tenant_memberships.tenant_id", "tenant_memberships.user_id"],
            ondelete="CASCADE",
            name="fk_tenant_user_roles_membership",
        ),
        ForeignKeyConstraint(
            ["role_id", "tenant_id"],
            ["tenant_roles.id", "tenant_roles.tenant_id"],
            ondelete="CASCADE",
            name="fk_tenant_user_roles_role_tenant",
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    role_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class TenantAgentGrantRecord(Base):
    """Agent-level permissions a role grants on one agent of the same tenant."""

    __tablename__ = "tenant_agent_grants"
    __table_args__ = (
        ForeignKeyConstraint(
            ["agent_id", "tenant_id"], ["agents.id", "agents.tenant_id"],
            ondelete="CASCADE", name="fk_tenant_agent_grants_agent_tenant",
        ),
        ForeignKeyConstraint(
            ["role_id", "tenant_id"], ["tenant_roles.id", "tenant_roles.tenant_id"],
            ondelete="CASCADE", name="fk_tenant_agent_grants_role_tenant",
        ),
    )

    role_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    agent_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    permission: Mapped[str] = mapped_column(String(16), primary_key=True)
