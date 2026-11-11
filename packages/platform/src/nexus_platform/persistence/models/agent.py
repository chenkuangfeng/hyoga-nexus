"""SQLAlchemy agent mappings; domain-owned tables with their existing columns and constraints."""
from __future__ import annotations
from datetime import datetime
from typing import Any
from uuid import UUID
from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column
from ..base import Base


class AgentRecord(Base):
    __tablename__ = "agents"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_agents_tenant_name"),
        UniqueConstraint("id", "tenant_id", name="uq_agents_id_tenant"),
        ForeignKeyConstraint(
            ["draft_model_profile_version_id", "tenant_id"],
            ["model_profile_versions.id", "model_profile_versions.tenant_id"],
            ondelete="RESTRICT", name="fk_agents_draft_model_profile_tenant",
        ),
        CheckConstraint("status IN ('draft', 'published', 'archived')", name="ck_agents_status"),
        CheckConstraint("ownership IN ('personal', 'enterprise')", name="ck_agents_ownership"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="draft")
    #: ``personal``: created in the employee workspace and maintained only by its creator; ``enterprise``: created by
    #: enterprise administrators and maintained only by holders of ``enterprise_agents:manage``
    #: (openspec 2026-11-11-enterprise-saas, decision 2).
    ownership: Mapped[str] = mapped_column(String(16), nullable=False, default="personal")
    draft_runtime_type: Mapped[str] = mapped_column(String(48), nullable=False, default="native")
    draft_instructions: Mapped[str] = mapped_column(Text, nullable=False, default="")
    draft_model_profile_version_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    draft_budgets: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    published_version_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    version_counter: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_by: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AgentVersionRecord(Base):
    __tablename__ = "agent_versions"
    __table_args__ = (
        UniqueConstraint("agent_id", "version", name="uq_agent_versions_version"),
        UniqueConstraint("id", "tenant_id", name="uq_agent_versions_id_tenant"),
        ForeignKeyConstraint(
            ["agent_id", "tenant_id"], ["agents.id", "agents.tenant_id"],
            ondelete="CASCADE", name="fk_agent_versions_agent_tenant",
        ),
        ForeignKeyConstraint(
            ["model_profile_version_id", "tenant_id"],
            ["model_profile_versions.id", "model_profile_versions.tenant_id"],
            ondelete="RESTRICT", name="fk_agent_versions_model_profile_tenant",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    agent_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    runtime_type: Mapped[str] = mapped_column(String(48), nullable=False)
    instructions: Mapped[str] = mapped_column(Text, nullable=False)
    model_profile_version_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    budgets: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ResourceBindingRecord(Base):
    __tablename__ = "agent_resource_bindings"
    __table_args__ = (
        UniqueConstraint(
            "agent_version_id", "kind", "resource_id", "resource_version_id", "source_tenant_id",
            name="uq_resource_binding"
        ),
        ForeignKeyConstraint(
            ["source_tenant_id", "kind", "resource_id", "resource_version_id"],
            ["platform_resources.tenant_id", "platform_resources.kind", "platform_resources.resource_id",
             "platform_resources.version_id"],
            ondelete="RESTRICT", name="fk_resource_binding_registered_resource",
        ),
        Index("ix_resource_bindings_resource", "kind", "resource_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    agent_version_id: Mapped[UUID] = mapped_column(ForeignKey("agent_versions.id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(255), nullable=False)
    resource_version_id: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    source_tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False
    )
    binding_config: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


class AgentDraftBindingRecord(Base):
    __tablename__ = "agent_draft_bindings"
    __table_args__ = (
        UniqueConstraint(
            "agent_id", "kind", "resource_id", "resource_version_id", "source_tenant_id",
            name="uq_agent_draft_binding"
        ),
        ForeignKeyConstraint(
            ["source_tenant_id", "kind", "resource_id", "resource_version_id"],
            ["platform_resources.tenant_id", "platform_resources.kind", "platform_resources.resource_id",
             "platform_resources.version_id"],
            ondelete="RESTRICT", name="fk_agent_draft_registered_resource",
        ),
        Index("ix_agent_draft_bindings_resource", "kind", "resource_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    agent_id: Mapped[UUID] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(255), nullable=False)
    resource_version_id: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    source_tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False
    )
    binding_config: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
