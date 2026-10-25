from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
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
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    type_annotation_map = {dict[str, Any]: JSON().with_variant(JSONB(), "postgresql")}


class UserRecord(Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("issuer", "subject", name="uq_users_issuer_subject"),)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    issuer: Mapped[str] = mapped_column(String(128), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class WorkspaceRecord(Base):
    __tablename__ = "workspaces"
    __table_args__ = (CheckConstraint("status IN ('active', 'archived')", name="ck_workspaces_status"),)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="active")
    created_by: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MembershipRecord(Base):
    __tablename__ = "workspace_memberships"
    __table_args__ = (
        CheckConstraint("role IN ('owner', 'admin', 'member')", name="ck_membership_role"),
        CheckConstraint("status IN ('active', 'revoked')", name="ck_membership_status"),
        Index("ix_memberships_user_status", "user_id", "status"),
    )

    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


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


class ModelProfileRecord(Base):
    __tablename__ = "model_profiles"
    __table_args__ = (
        UniqueConstraint("workspace_id", "name", name="uq_model_profiles_workspace_name"),
        UniqueConstraint("id", "workspace_id", name="uq_model_profiles_id_workspace"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    current_version_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    created_by: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ModelProfileVersionRecord(Base):
    __tablename__ = "model_profile_versions"
    __table_args__ = (
        UniqueConstraint("profile_id", "version", name="uq_model_profile_versions_version"),
        UniqueConstraint("id", "workspace_id", name="uq_model_profile_versions_id_workspace"),
        ForeignKeyConstraint(
            ["profile_id", "workspace_id"], ["model_profiles.id", "model_profiles.workspace_id"],
            ondelete="CASCADE", name="fk_model_profile_versions_profile_workspace",
        ),
        ForeignKeyConstraint(
            ["credential_reference_id", "workspace_id"],
            ["credential_references.id", "credential_references.workspace_id"],
            ondelete="RESTRICT", name="fk_model_profile_versions_credential_workspace",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    profile_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    model_name: Mapped[str] = mapped_column(String(160), nullable=False)
    options: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    credential_reference_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AgentRecord(Base):
    __tablename__ = "agents"
    __table_args__ = (
        UniqueConstraint("workspace_id", "name", name="uq_agents_workspace_name"),
        UniqueConstraint("id", "workspace_id", name="uq_agents_id_workspace"),
        ForeignKeyConstraint(
            ["draft_model_profile_version_id", "workspace_id"],
            ["model_profile_versions.id", "model_profile_versions.workspace_id"],
            ondelete="RESTRICT", name="fk_agents_draft_model_profile_workspace",
        ),
        CheckConstraint("status IN ('draft', 'published', 'archived')", name="ck_agents_status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="draft")
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
        UniqueConstraint("id", "workspace_id", name="uq_agent_versions_id_workspace"),
        ForeignKeyConstraint(
            ["agent_id", "workspace_id"], ["agents.id", "agents.workspace_id"],
            ondelete="CASCADE", name="fk_agent_versions_agent_workspace",
        ),
        ForeignKeyConstraint(
            ["model_profile_version_id", "workspace_id"],
            ["model_profile_versions.id", "model_profile_versions.workspace_id"],
            ondelete="RESTRICT", name="fk_agent_versions_model_profile_workspace",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    agent_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
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
            "agent_version_id", "kind", "resource_id", "resource_version_id", "source_workspace_id",
            name="uq_resource_binding"
        ),
        ForeignKeyConstraint(
            ["source_workspace_id", "kind", "resource_id", "resource_version_id"],
            ["platform_resources.workspace_id", "platform_resources.kind", "platform_resources.resource_id",
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
    source_workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=False
    )
    binding_config: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


class AgentDraftBindingRecord(Base):
    __tablename__ = "agent_draft_bindings"
    __table_args__ = (
        UniqueConstraint(
            "agent_id", "kind", "resource_id", "resource_version_id", "source_workspace_id",
            name="uq_agent_draft_binding"
        ),
        ForeignKeyConstraint(
            ["source_workspace_id", "kind", "resource_id", "resource_version_id"],
            ["platform_resources.workspace_id", "platform_resources.kind", "platform_resources.resource_id",
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
    source_workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=False
    )
    binding_config: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


class PlatformResourceRecord(Base):
    """Authorization metadata registered by owning resource packages; not resource content."""

    __tablename__ = "platform_resources"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "kind", "resource_id", "version_id", name="uq_platform_resources_version"
        ),
        Index("ix_platform_resources_lookup", "workspace_id", "kind", "resource_id", "active"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(255), nullable=False)
    version_id: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ResourceGrantRecord(Base):
    __tablename__ = "resource_grants"
    __table_args__ = (
        UniqueConstraint(
            "source_workspace_id", "target_workspace_id", "kind", "resource_id", name="uq_resource_grant"
        ),
        Index("ix_resource_grants_target", "target_workspace_id", "kind", "resource_id", "revoked_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    source_workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    target_workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(255), nullable=False)
    permissions: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    created_by: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SessionRecord(Base):
    __tablename__ = "sessions"
    __table_args__ = (
        UniqueConstraint("id", "workspace_id", name="uq_sessions_id_workspace"),
        ForeignKeyConstraint(
            ["agent_version_id", "workspace_id"], ["agent_versions.id", "agent_versions.workspace_id"],
            ondelete="RESTRICT", name="fk_sessions_agent_version_workspace",
        ),
        Index("ix_sessions_workspace_updated", "workspace_id", "updated_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    owner_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    agent_version_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    runtime_type: Mapped[str] = mapped_column(String(48), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MessageRecord(Base):
    __tablename__ = "messages"
    __table_args__ = (UniqueConstraint("session_id", "sequence", name="uq_messages_session_sequence"),)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    session_id: Mapped[UUID] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False)
    run_id: Mapped[UUID | None] = mapped_column(ForeignKey("runs.id", ondelete="SET NULL"))
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(String(24), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    runtime_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class RunRecord(Base):
    __tablename__ = "runs"
    __table_args__ = (
        UniqueConstraint("workspace_id", "principal_id", "idempotency_key", name="uq_runs_idempotency"),
        ForeignKeyConstraint(
            ["session_id", "workspace_id"], ["sessions.id", "sessions.workspace_id"],
            ondelete="CASCADE", name="fk_runs_session_workspace",
        ),
        CheckConstraint(
            "status IN ('queued','running','waiting_input','waiting_approval','completed','failed','cancelled','interrupted')",
            name="ck_runs_status",
        ),
        Index("uq_runs_active_session", "session_id", unique=True,
              sqlite_where=text("status IN ('queued','running','waiting_input','waiting_approval')"),
              postgresql_where=text("status IN ('queued','running','waiting_input','waiting_approval')")),
        Index("ix_runs_session_created", "session_id", "created_at"),
        Index("ix_runs_lease", "status", "lease_until"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    session_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    principal_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    config_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lease_owner: Mapped[str | None] = mapped_column(String(160))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RunEventRecord(Base):
    __tablename__ = "run_events"
    __table_args__ = (UniqueConstraint("run_id", "sequence", name="uq_run_events_sequence"),)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ToolInvocationRecord(Base):
    __tablename__ = "tool_invocations"
    __table_args__ = (Index("uq_tool_invocations_operation", "run_id", "operation_id", unique=True),)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), nullable=False)
    resource_binding_id: Mapped[UUID | None] = mapped_column(ForeignKey("agent_resource_bindings.id", ondelete="SET NULL"))
    operation_id: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    input_summary: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    output_summary: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    error_code: Mapped[str | None] = mapped_column(String(80))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RuntimeSessionBindingRecord(Base):
    __tablename__ = "runtime_session_bindings"
    __table_args__ = (
        UniqueConstraint("session_id", "runtime_type", "runtime_scope", name="uq_runtime_session_scope"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    session_id: Mapped[UUID] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False)
    runtime_type: Mapped[str] = mapped_column(String(48), nullable=False)
    runtime_scope: Mapped[str] = mapped_column(String(255), nullable=False)
    external_session_id: Mapped[str] = mapped_column(String(512), nullable=False)
    recovery_capabilities: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AuditRecord(Base):
    __tablename__ = "audit_records"
    __table_args__ = (Index("ix_audit_workspace_time", "workspace_id", "created_at"),)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    actor_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    target_type: Mapped[str] = mapped_column(String(80), nullable=False)
    target_id: Mapped[str] = mapped_column(String(255), nullable=False)
    result: Mapped[str] = mapped_column(String(24), nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class OutboxRecord(Base):
    __tablename__ = "outbox_records"
    __table_args__ = (
        UniqueConstraint("run_id", "message_type", name="uq_outbox_run_type"),
        Index("ix_outbox_available", "completed_at", "available_at", "lease_until"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), nullable=False)
    message_type: Mapped[str] = mapped_column(String(100), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lease_owner: Mapped[str | None] = mapped_column(String(160))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class NativeRunStateRecord(Base):
    __tablename__ = 'native_run_states'
    run_id: Mapped[UUID] = mapped_column(ForeignKey('runs.id', ondelete='CASCADE'), primary_key=True)
    progress: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


class InputRequestRecord(Base):
    __tablename__ = 'run_input_requests'
    __table_args__ = (UniqueConstraint('run_id', 'response_key', name='uq_input_response_key'),)
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    run_id: Mapped[UUID] = mapped_column(ForeignKey('runs.id', ondelete='CASCADE'), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    response: Mapped[str | None] = mapped_column(Text)
    response_key: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WorkingCheckpointRecord(Base):
    __tablename__ = 'session_checkpoints'
    session_id: Mapped[UUID] = mapped_column(ForeignKey('sessions.id', ondelete='CASCADE'), primary_key=True)
    workspace_id: Mapped[UUID] = mapped_column(ForeignKey('workspaces.id', ondelete='CASCADE'), nullable=False)
    source_run_id: Mapped[UUID] = mapped_column(ForeignKey('runs.id', ondelete='CASCADE'), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MemoryDraftRecord(Base):
    __tablename__ = 'memory_drafts'
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    workspace_id: Mapped[UUID] = mapped_column(ForeignKey('workspaces.id', ondelete='CASCADE'), nullable=False)
    source_run_id: Mapped[UUID] = mapped_column(ForeignKey('runs.id', ondelete='CASCADE'), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    scope: Mapped[str] = mapped_column(String(255), nullable=False)
    diff: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default='pending_review')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ModelProviderRecord(Base):
    __tablename__ = 'model_providers'
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    workspace_id: Mapped[UUID] = mapped_column(ForeignKey('workspaces.id'), nullable=False)
    owner_user_id: Mapped[UUID | None] = mapped_column(ForeignKey('users.id'))
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    base_url: Mapped[str] = mapped_column(String(512), nullable=False)
    credential_id: Mapped[UUID] = mapped_column(ForeignKey('credential_references.id'), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_test_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProviderModelRecord(Base):
    __tablename__ = 'provider_models'
    profile_id: Mapped[UUID] = mapped_column(ForeignKey('model_profiles.id'), primary_key=True)
    provider_id: Mapped[UUID] = mapped_column(ForeignKey('model_providers.id'), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class ModelDefaultRecord(Base):
    __tablename__ = 'model_defaults'
    workspace_id: Mapped[UUID] = mapped_column(ForeignKey('workspaces.id'), primary_key=True)
    scope_key: Mapped[str] = mapped_column(String(36), primary_key=True)
    version_id: Mapped[UUID] = mapped_column(ForeignKey('model_profile_versions.id'), nullable=False)


class ProviderCredentialRecord(Base):
    __tablename__ = 'provider_credentials'
    credential_id: Mapped[UUID] = mapped_column(ForeignKey('credential_references.id'), primary_key=True)
    provider_id: Mapped[UUID] = mapped_column(ForeignKey('model_providers.id'), nullable=False)
    base_url: Mapped[str] = mapped_column(String(512), nullable=False)
    encrypted_key: Mapped[str] = mapped_column(Text, nullable=False)
