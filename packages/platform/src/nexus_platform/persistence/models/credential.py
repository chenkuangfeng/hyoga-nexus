"""SQLAlchemy credential mappings; domain-owned tables with their existing columns and constraints."""
from __future__ import annotations
from datetime import datetime
from typing import Any
from uuid import UUID
from sqlalchemy import JSON, DateTime, ForeignKey, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column
from ..base import Base


class CredentialReferenceRecord(Base):
    __tablename__ = "credential_references"
    __table_args__ = (UniqueConstraint("id", "workspace_id", name="uq_credential_refs_id_workspace"),)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    backend: Mapped[str] = mapped_column(String(80), nullable=False)
    handle: Mapped[str] = mapped_column(String(512), nullable=False)
    scope: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ProviderCredentialRecord(Base):
    """Authenticated encrypted secret bound to one provider, reference and historical destination."""

    __tablename__ = 'provider_credentials'
    credential_id: Mapped[UUID] = mapped_column(ForeignKey('credential_references.id'), primary_key=True)
    provider_id: Mapped[UUID] = mapped_column(ForeignKey('model_providers.id'), nullable=False)
    base_url: Mapped[str] = mapped_column(String(512), nullable=False)
    encrypted_key: Mapped[str] = mapped_column(Text, nullable=False)
