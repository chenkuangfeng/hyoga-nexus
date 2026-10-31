"""SQLAlchemy model mappings; domain-owned tables with their existing columns and constraints."""
from __future__ import annotations
from datetime import datetime
from typing import Any
from uuid import UUID
from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column
from ..base import Base


class ModelProfileRecord(Base):
    __tablename__ = "model_profiles"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_model_profiles_tenant_name"),
        UniqueConstraint("id", "tenant_id", name="uq_model_profiles_id_tenant"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    current_version_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    created_by: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ModelProfileVersionRecord(Base):
    __tablename__ = "model_profile_versions"
    __table_args__ = (
        UniqueConstraint("profile_id", "version", name="uq_model_profile_versions_version"),
        UniqueConstraint("id", "tenant_id", name="uq_model_profile_versions_id_tenant"),
        ForeignKeyConstraint(
            ["profile_id", "tenant_id"], ["model_profiles.id", "model_profiles.tenant_id"],
            ondelete="CASCADE", name="fk_model_profile_versions_profile_tenant",
        ),
        ForeignKeyConstraint(
            ["credential_reference_id", "tenant_id"],
            ["credential_references.id", "credential_references.tenant_id"],
            ondelete="RESTRICT", name="fk_model_profile_versions_credential_tenant",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    profile_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    model_name: Mapped[str] = mapped_column(String(160), nullable=False)
    options: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    credential_reference_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ModelProviderRecord(Base):
    """Tenant-scoped provider; a non-null owner restricts all use to that user."""

    __tablename__ = 'model_providers'
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey('tenants.id'), nullable=False)
    owner_user_id: Mapped[UUID | None] = mapped_column(ForeignKey('users.id'))
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    base_url: Mapped[str] = mapped_column(String(512), nullable=False)
    credential_id: Mapped[UUID] = mapped_column(ForeignKey('credential_references.id'), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_test_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProviderModelRecord(Base):
    """Active association between a provider and an immutable-version model profile."""

    __tablename__ = 'provider_models'
    profile_id: Mapped[UUID] = mapped_column(ForeignKey('model_profiles.id'), primary_key=True)
    provider_id: Mapped[UUID] = mapped_column(ForeignKey('model_providers.id'), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class ModelDefaultRecord(Base):
    """Per-Tenant personal UUID or tenant preference; never an execution override."""

    __tablename__ = 'model_defaults'
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey('tenants.id'), primary_key=True)
    scope_key: Mapped[str] = mapped_column(String(36), primary_key=True)
    version_id: Mapped[UUID] = mapped_column(ForeignKey('model_profile_versions.id'), nullable=False)
