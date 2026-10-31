"""SQLAlchemy run mappings; domain-owned tables with their existing columns and constraints."""
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
    text,
)
from sqlalchemy.orm import Mapped, mapped_column
from ..base import Base


class RunRecord(Base):
    __tablename__ = "runs"
    __table_args__ = (
        UniqueConstraint("tenant_id", "principal_id", "idempotency_key", name="uq_runs_idempotency"),
        ForeignKeyConstraint(
            ["session_id", "tenant_id"], ["sessions.id", "sessions.tenant_id"],
            ondelete="CASCADE", name="fk_runs_session_tenant",
        ),
        CheckConstraint(
            "status IN ('queued','running','waiting_input','waiting_approval','completed','failed','cancelled','interrupted')",
            name="ck_runs_status",
        ),
        # At most one executing Run per session. Queued Runs are not constrained here: their order
        # and admission are owned by the dispatch ledger (session_admissions).
        Index("uq_runs_active_session", "session_id", unique=True,
              sqlite_where=text("status IN ('running','waiting_input','waiting_approval')"),
              postgresql_where=text("status IN ('running','waiting_input','waiting_approval')")),
        Index("ix_runs_session_created", "session_id", "created_at"),
        Index("ix_runs_lease", "status", "lease_until"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
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


class NativeRunStateRecord(Base):
    __tablename__ = 'native_run_states'
    run_id: Mapped[UUID] = mapped_column(ForeignKey('runs.id', ondelete='CASCADE'), primary_key=True)
    progress: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


class RunDirectiveRecord(Base):
    """Ordered, idempotent user corrections persisted before model context consumption."""
    __tablename__ = 'run_directives'
    __table_args__ = (UniqueConstraint('run_id', 'idempotency_key', name='uq_run_directive_key'),)
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    run_id: Mapped[UUID] = mapped_column(ForeignKey('runs.id'), nullable=False)
    principal_id: Mapped[UUID] = mapped_column(ForeignKey('users.id'), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class NativePreferenceRecord(Base):
    """Versioned personal Native defaults; published AgentVersions keep their snapshots."""
    __tablename__ = 'native_preferences'
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey('tenants.id'), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey('users.id'), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    settings: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
