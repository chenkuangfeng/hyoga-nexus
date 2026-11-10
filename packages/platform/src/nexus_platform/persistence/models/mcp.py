"""MCP domain tables (openspec 2026-11-08-mcp).

Secrets never land in these tables as plaintext: connection config stores credential-reference
markers only, and OAuth client secrets / tokens are encrypted with the deployment key.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (JSON, Boolean, DateTime, ForeignKey, Index, Integer, String, Text,
                        UniqueConstraint, Uuid)
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base


class McpServiceRecord(Base):
    """One external MCP server inside one Tenant. `config` holds transport + connection parameters
    with secrets as credential-reference markers; resolved values are never persisted."""

    __tablename__ = "mcp_services"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_mcp_services_tenant_name"),
        Index("ix_mcp_services_tenant", "tenant_id", "enabled"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    transport: Mapped[str] = mapped_column(String(24), nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    #: Opaque lifecycle epoch; bumped on delete + identical re-add so a stale session is never reused.
    config_epoch: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class McpServiceToolRecord(Base):
    """Discovered-tool cache and the per-tool enable whitelist in one table."""

    __tablename__ = "mcp_service_tools"
    __table_args__ = (
        Index("ix_mcp_service_tools_service", "service_id", "catalog_status"),
    )

    service_id: Mapped[UUID] = mapped_column(ForeignKey("mcp_services.id", ondelete="CASCADE"), primary_key=True)
    tool_name: Mapped[str] = mapped_column(String(255), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    input_schema: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    output_schema: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    read_only_hint: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    #: loading / ready / error (WeKnora catalog status machine).
    catalog_status: Mapped[str] = mapped_column(String(16), nullable=False, default="loading")
    catalog_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Secret-safe connection fingerprint that produced this cache row.
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    #: Service lifecycle epoch captured at discovery, so a re-added service invalidates the row.
    config_epoch: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class McpToolApprovalRecord(Base):
    """Stored risk policy per (tenant, service, tool); the effective risk is derived, never stored."""

    __tablename__ = "mcp_tool_approvals"
    __table_args__ = (
        UniqueConstraint("tenant_id", "service_id", "tool_name", name="uq_mcp_tool_approvals"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    service_id: Mapped[UUID] = mapped_column(ForeignKey("mcp_services.id", ondelete="CASCADE"), nullable=False)
    tool_name: Mapped[str] = mapped_column(String(255), nullable=False)
    #: read / write / destructive; None until the workspace sets one.
    explicit_risk: Mapped[str | None] = mapped_column(String(16), nullable=True)
    #: Highest risk the service ever declared.
    observed_risk: Mapped[str | None] = mapped_column(String(16), nullable=True)
    require_approval: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    #: Set when the service now declares lower than observed; workspace confirmation clears it.
    pending_downgrade: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class McpOAuthClientRecord(Base):
    """Dynamically registered OAuth client (RFC 9728) per (tenant, service)."""

    __tablename__ = "mcp_oauth_clients"
    __table_args__ = (
        UniqueConstraint("tenant_id", "service_id", name="uq_mcp_oauth_clients"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    service_id: Mapped[UUID] = mapped_column(ForeignKey("mcp_services.id", ondelete="CASCADE"), nullable=False)
    client_id: Mapped[str] = mapped_column(String(512), nullable=False)
    client_secret: Mapped[str] = mapped_column(Text, nullable=True)
    redirect_uri: Mapped[str] = mapped_column(String(1024), nullable=False)
    auth_server_metadata_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    registration_access_token: Mapped[str] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class McpOAuthTokenRecord(Base):
    """OAuth tokens scoped by (tenant, principal, service); never shared across users."""

    __tablename__ = "mcp_oauth_tokens"

    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True)
    principal_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    service_id: Mapped[UUID] = mapped_column(ForeignKey("mcp_services.id", ondelete="CASCADE"), primary_key=True)
    access_token: Mapped[str] = mapped_column(Text, nullable=False)
    refresh_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    scope: Mapped[str] = mapped_column(Text, nullable=False, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class McpEndpointRecord(Base):
    """One outbound MCP endpoint exposing a read-only tool face to external MCP clients.

    The plaintext long-lived token appears only in the create/rotate response; ``token_hash`` is a
    SHA-256 digest. ``tool_allowlist`` names the read-only tools this endpoint exposes; ``kb_ids``
    bounds knowledge search (empty = every readable base).
    """

    __tablename__ = "mcp_endpoints"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_mcp_endpoints_tenant_name"),
        Index("ix_mcp_endpoints_tenant", "tenant_id", "enabled"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    #: Names of the read-only tools this endpoint exposes (whitelist).
    tool_allowlist: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    #: Knowledge-base ids searchable through this endpoint (empty = every readable base).
    kb_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    #: SHA-256 of the long-lived endpoint token; empty after revocation.
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
