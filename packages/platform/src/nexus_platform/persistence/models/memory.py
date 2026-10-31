"""SQLAlchemy memory mappings; domain-owned tables with their existing columns and constraints."""
from __future__ import annotations
from datetime import datetime
from uuid import UUID
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column
from ..base import Base


class WorkingCheckpointRecord(Base):
    __tablename__ = 'session_checkpoints'
    session_id: Mapped[UUID] = mapped_column(ForeignKey('sessions.id', ondelete='CASCADE'), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False)
    source_run_id: Mapped[UUID] = mapped_column(ForeignKey('runs.id', ondelete='CASCADE'), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MemoryDraftRecord(Base):
    __tablename__ = 'memory_drafts'
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False)
    source_run_id: Mapped[UUID] = mapped_column(ForeignKey('runs.id', ondelete='CASCADE'), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    scope: Mapped[str] = mapped_column(String(255), nullable=False)
    diff: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default='pending_review')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MemoryEntryRecord(Base):
    """Private published memory/SOP identity, separate from knowledge documents and drafts."""
    __tablename__ = 'memory_entries'
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey('tenants.id'), nullable=False)
    owner_user_id: Mapped[UUID] = mapped_column(ForeignKey('users.id'), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    project: Mapped[str] = mapped_column(String(160), nullable=False, default='')
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    current_version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MemoryVersionRecord(Base):
    """Immutable reviewed content and original Run provenance; rollback creates another version."""
    __tablename__ = 'memory_versions'
    entry_id: Mapped[UUID] = mapped_column(ForeignKey('memory_entries.id'), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source_run_id: Mapped[UUID] = mapped_column(ForeignKey('runs.id'), nullable=False)
    source_draft_id: Mapped[UUID] = mapped_column(ForeignKey('memory_drafts.id'), nullable=False)
    reviewed_by: Mapped[UUID] = mapped_column(ForeignKey('users.id'), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ContextSummaryRecord(Base):
    """Cross-Run summary cutpoint tied to original stored messages and source authorization."""
    __tablename__ = 'context_summaries'
    session_id: Mapped[UUID] = mapped_column(ForeignKey('sessions.id'), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey('tenants.id'), nullable=False)
    source_run_id: Mapped[UUID] = mapped_column(ForeignKey('runs.id'), nullable=False)
    through_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
