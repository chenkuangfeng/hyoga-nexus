"""Durable model request snapshots used by the read-only trajectory inspector."""
from __future__ import annotations
from datetime import datetime
from typing import Any
from uuid import UUID
from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column
from ..base import Base


class RunTrajectoryRecord(Base):
    __tablename__ = 'run_trajectory_records'
    __table_args__ = (
        UniqueConstraint('run_id', 'sequence', name='uq_run_trajectory_sequence'),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    run_id: Mapped[UUID] = mapped_column(ForeignKey('runs.id', ondelete='CASCADE'), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    turn: Mapped[int] = mapped_column(Integer, nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    purpose: Mapped[str] = mapped_column(String(24), nullable=False, default='assistant')
    status: Mapped[str] = mapped_column(String(24), nullable=False, default='running')
    input_estimate_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    run_total_tokens: Mapped[int | None] = mapped_column(Integer)
    request_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    response_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    usage: Mapped[dict[str, int]] = mapped_column(JSON, nullable=False, default=dict)
    error_code: Mapped[str | None] = mapped_column(String(100))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
