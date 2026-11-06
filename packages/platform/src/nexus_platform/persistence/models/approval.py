"""SQLAlchemy approval mappings; domain-owned tables with their existing columns and constraints."""
from __future__ import annotations
from datetime import datetime
from uuid import UUID
from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, Index, String, Text, UniqueConstraint, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column
from ..base import Base


class InputRequestRecord(Base):
    __tablename__ = 'run_input_requests'
    __table_args__ = (UniqueConstraint('run_id', 'response_key', name='uq_input_response_key'),)
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    run_id: Mapped[UUID] = mapped_column(ForeignKey('runs.id', ondelete='CASCADE'), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    candidates: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    response: Mapped[str | None] = mapped_column(Text)
    response_key: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ActionApprovalRecord(Base):
    """One action decision, consumed only once under the original Run/binding hash."""
    __tablename__ = 'action_approvals'
    __table_args__ = (UniqueConstraint('run_id', 'tool_call_id', name='uq_action_approval_call'),)
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    run_id: Mapped[UUID] = mapped_column(ForeignKey('runs.id'), nullable=False)
    tool_call_id: Mapped[str] = mapped_column(String(255), nullable=False)
    tool_name: Mapped[str] = mapped_column(String(64), nullable=False)
    arguments: Mapped[str] = mapped_column(Text, nullable=False)
    modified_arguments: Mapped[str | None] = mapped_column(Text)
    binding_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: Why approval was asked (tool-call-hardening): `policy` (access level or `requires_approval`) may be
    #: remembered for the session; `guard` (an argument guard rule matched) never may.
    reason: Mapped[str] = mapped_column(String(8), nullable=False, default='policy', server_default='policy')
    #: The tool's risk when approval was asked; `destructive` approvals cannot be remembered.
    risk: Mapped[str | None] = mapped_column(String(16))


class ActionGrantRecord(Base):
    """ActionGrant (architecture 2.11): an owner's standing approval of one tool (tool-call-hardening E).

    Only `scope='session'` is used: `scope_id` is the session, and the grant applies to calls of
    `tool_name` by Runs of `agent_version_id` in that session (a new agent version asks again). Grants are
    looked up on every call, so revocation (`revoked_at`) takes effect immediately.
    """
    __tablename__ = 'action_grants'
    __table_args__ = (
        CheckConstraint("scope IN ('session','automation')", name='ck_action_grants_scope'),
        Index('uq_action_grants_active', 'scope', 'scope_id', 'agent_version_id', 'tool_name', unique=True,
              sqlite_where=text('revoked_at IS NULL'), postgresql_where=text('revoked_at IS NULL')),
    )
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False)
    principal_id: Mapped[UUID] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    scope: Mapped[str] = mapped_column(String(16), nullable=False)
    scope_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    agent_version_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    tool_name: Mapped[str] = mapped_column(String(64), nullable=False)
    risk: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
