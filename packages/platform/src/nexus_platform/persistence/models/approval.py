"""SQLAlchemy approval mappings; domain-owned tables with their existing columns and constraints."""
from __future__ import annotations
from datetime import datetime
from uuid import UUID
from sqlalchemy import JSON, DateTime, ForeignKey, String, Text, UniqueConstraint, Uuid
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
