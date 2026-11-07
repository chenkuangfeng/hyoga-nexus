"""Scheduled agent runs (openspec 2026-11-07-tool-expansion, section 8.2).

One job pins one agent version and owns one session; every fire adds a message and a Run to that session, so the
conversation history of a job reads as one thread and a Run can be recognised as unattended by its session.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base


class CronJobRecord(Base):
    __tablename__ = 'cron_jobs'
    __table_args__ = (UniqueConstraint('session_id', name='uq_cron_jobs_session'),
                      Index('ix_cron_jobs_due', 'state', 'next_run_at'),
                      Index('ix_cron_jobs_owner', 'tenant_id', 'owner_user_id'))
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False)
    owner_user_id: Mapped[UUID] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    agent_version_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    session_id: Mapped[UUID] = mapped_column(ForeignKey('sessions.id', ondelete='CASCADE'), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    rule: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    #: `active`, `paused` (by the owner) or `suspended` (by the scheduler; `last_error` says why).
    state: Mapped[str] = mapped_column(String(16), nullable=False, default='active')
    next_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_run_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    last_error: Mapped[str] = mapped_column(String(120), nullable=False, default='')
    run_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
