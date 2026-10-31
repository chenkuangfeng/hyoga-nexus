"""Dispatch ledger mappings: process epoch and per-session admission queue.

The ledger is shared by the single-machine (SQLite) and multi-tenant (PostgreSQL)
backends. Its rules live in ``nexus_platform.runs.session_ledger``; these mappings
only describe the tables. Status values are constrained by a CHECK constraint so a
bad write fails in the database, not later during recovery.
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base

ADMISSION_STATUSES = ("queued", "started", "unknown", "terminal")


class RuntimeEpochRecord(Base):
    """Singleton row whose ``epoch`` increases each time a worker or gateway process starts."""

    __tablename__ = "runtime_epoch"
    __table_args__ = (CheckConstraint("singleton = 1", name="ck_runtime_epoch_singleton"),)

    singleton: Mapped[int] = mapped_column(Integer, primary_key=True)
    epoch: Mapped[int] = mapped_column(Integer, nullable=False)
    instance_id: Mapped[str] = mapped_column(String(160), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SessionAdmissionRecord(Base):
    """One accepted input waiting for, or occupying, its session's execution slot.

    ``seq`` orders the FIFO and is the primary key so SQLite autoincrement works.
    ``owner_epoch`` records which process generation claimed the row; it is what
    startup recovery compares against the current epoch.
    """

    __tablename__ = "session_admissions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'started', 'unknown', 'terminal')",
            name="ck_session_admissions_status",
        ),
        Index("ix_session_admissions_session_status", "session_id", "status"),
    )

    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    admission_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, unique=True)
    session_id: Mapped[UUID] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False,
    )
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, unique=True,
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    owner_epoch: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
