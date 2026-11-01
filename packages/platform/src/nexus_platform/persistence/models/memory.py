"""SQLAlchemy memory mappings; domain-owned tables with their existing columns and constraints.

Storage layers (memory design 9.2): drafts are candidates and never retrieved; entries and their
immutable versions are the published facts; `memory_fts` is a derived SQLite keyword index that is
kept in the same transaction as publication and can be rebuilt from `memory_versions.tokens`.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import JSON, Boolean, CheckConstraint, DDL, DateTime, ForeignKey, Index, Integer, String, Text, Uuid, event, text
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base

#: Keyword index for SQLite. Contentless: text lives in `memory_versions.tokens`, joined by `search_id`.
#: `contentless_delete` allows deleting a version's row when it is superseded (SQLite >= 3.43).
MEMORY_FTS_DDL = (
    "CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5("
    "tokens, content='', contentless_delete=1, tokenize='unicode61')"
)


class WorkingCheckpointRecord(Base):
    __tablename__ = 'session_checkpoints'
    session_id: Mapped[UUID] = mapped_column(ForeignKey('sessions.id', ondelete='CASCADE'), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False)
    source_run_id: Mapped[UUID] = mapped_column(ForeignKey('runs.id', ondelete='CASCADE'), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MemoryDraftRecord(Base):
    __tablename__ = 'memory_drafts'
    __table_args__ = (Index('ix_memory_drafts_fingerprint', 'tenant_id', 'fingerprint'),)
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False)
    source_run_id: Mapped[UUID] = mapped_column(ForeignKey('runs.id', ondelete='CASCADE'), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    scope: Mapped[str] = mapped_column(String(255), nullable=False)
    diff: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default='pending_review')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    origin: Mapped[str] = mapped_column(String(16), nullable=False, default='foreground', server_default='foreground')
    fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    base_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_message_ids: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)


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
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default='1')
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class MemoryVersionRecord(Base):
    """Immutable reviewed content and original Run provenance; rollback creates another version."""
    __tablename__ = 'memory_versions'
    __table_args__ = (Index('uq_memory_versions_search_id', 'search_id', unique=True),)
    entry_id: Mapped[UUID] = mapped_column(ForeignKey('memory_entries.id'), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source_run_id: Mapped[UUID] = mapped_column(ForeignKey('runs.id'), nullable=False)
    source_draft_id: Mapped[UUID] = mapped_column(ForeignKey('memory_drafts.id'), nullable=False)
    reviewed_by: Mapped[UUID] = mapped_column(ForeignKey('users.id'), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tokens: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Stable integer key used as the FTS rowid. An explicit column is used because SQLite may renumber
    #: implicit rowids (for example on VACUUM), which would silently misalign the keyword index.
    search_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_message_ids: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)


class MemoryTombstoneRecord(Base):
    """Content the owner rejected; the same fingerprint is not proposed again."""
    __tablename__ = 'memory_tombstones'
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey('tenants.id', ondelete='CASCADE'), primary_key=True)
    owner_user_id: Mapped[UUID] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(64), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ContextSummaryRecord(Base):
    """Append-only summary cutpoint tied to original stored messages and source authorization.

    Each compaction inserts a row whose `supersedes_id` names the summary it replaces; rows are never
    updated. The effective summary is the one with the largest `through_sequence` that nothing supersedes.
    `source_run_id` is the Run that produced the summary.
    """
    __tablename__ = 'context_summaries'
    __table_args__ = (Index('ix_context_summaries_session_through', 'session_id', 'through_sequence'),)
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    session_id: Mapped[UUID] = mapped_column(ForeignKey('sessions.id'), nullable=False)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey('tenants.id'), nullable=False)
    source_run_id: Mapped[UUID] = mapped_column(ForeignKey('runs.id'), nullable=False)
    through_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    supersedes_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


#: `contentless_delete` needs SQLite 3.43; older builds or drivers without FTS5 keep the LIKE fallback.
FTS_MIN_SQLITE = (3, 43, 0)
_FTS_PROBE = "CREATE VIRTUAL TABLE temp.memory_fts_probe USING fts5(x, tokenize='unicode61')"


def keyword_index_supported(connection) -> bool:
    """True when this SQLite build can create the contentless FTS5 table (version and module probe)."""
    if sqlite3.sqlite_version_info < FTS_MIN_SQLITE:
        return False
    try:
        connection.exec_driver_sql(_FTS_PROBE)
        connection.exec_driver_sql('DROP TABLE temp.memory_fts_probe')
    except Exception:  # driver built without FTS5: the search path falls back to LIKE
        return False
    return True


# Create the keyword index whenever the schema is created on SQLite (tests and local installs use
# `create_all`; deployed databases get it from the migration). PostgreSQL skips this statement.
event.listen(Base.metadata, 'after_create', DDL(MEMORY_FTS_DDL).execute_if(
    dialect='sqlite', callable_=lambda ddl, target, connection, **kw: keyword_index_supported(connection)))


class SessionMemorySnapshotRecord(Base):
    """The owner's published-memory index frozen for one session (openspec 2026-11-01-memory-optimization, stage 2).

    One row per session, created by the session's first Run and reused by later Runs so the system prefix
    stays byte-stable. `version_key` fingerprints the owner's published entries at creation time; it lets
    the API report that the snapshot is older than the current memory, but never triggers a refresh by itself.
    Deleting the row (explicit refresh) makes the next Run build a new snapshot.
    """
    __tablename__ = 'session_memory_snapshots'
    session_id: Mapped[UUID] = mapped_column(ForeignKey('sessions.id', ondelete='CASCADE'), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False)
    owner_user_id: Mapped[UUID] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    index_text: Mapped[str] = mapped_column(Text, nullable=False)
    version_key: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MemoryCaptureSettingsRecord(Base):
    """Owner's automatic-capture switch and capture model (openspec 2026-11-01-memory-optimization, stage 3).

    Off by default. Enabling requires a memory model profile; the model is authorized on every extraction.
    """
    __tablename__ = 'memory_capture_settings'
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey('tenants.id', ondelete='CASCADE'), primary_key=True)
    owner_user_id: Mapped[UUID] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text('0'))
    model_profile_version_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MemoryCaptureCursorRecord(Base):
    """Highest message sequence already turned into capture jobs for one session (the cursor of 4.1)."""
    __tablename__ = 'memory_capture_cursors'
    session_id: Mapped[UUID] = mapped_column(ForeignKey('sessions.id', ondelete='CASCADE'), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False)
    owner_user_id: Mapped[UUID] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    last_processed_sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MemoryCaptureJobRecord(Base):
    """One extraction task. States: pending -> extracted -> stored -> completed; any step may fail.

    Each step commits with its effects (actions, drafts, cursor), so a crash resumes at the last committed
    step. `stored_count` makes draft creation idempotent: a restart continues after the drafts already made.
    """
    __tablename__ = 'memory_capture_jobs'
    __table_args__ = (
        Index('ix_memory_capture_jobs_owner_state', 'tenant_id', 'owner_user_id', 'state'),
        CheckConstraint("state IN ('pending','extracted','stored','completed','failed')",
                        name='ck_memory_capture_jobs_state'),
    )
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False)
    owner_user_id: Mapped[UUID] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    session_id: Mapped[UUID] = mapped_column(ForeignKey('sessions.id', ondelete='CASCADE'), nullable=False)
    source_run_id: Mapped[UUID] = mapped_column(ForeignKey('runs.id', ondelete='CASCADE'), nullable=False)
    from_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    through_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default='pending')
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_owner: Mapped[str | None] = mapped_column(String(128))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(500))
    actions: Mapped[list[Any] | None] = mapped_column(JSON)
    stored_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
