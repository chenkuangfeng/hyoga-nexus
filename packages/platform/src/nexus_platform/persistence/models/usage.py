"""Token usage and monthly limits (openspec 2026-11-11-enterprise-saas E6).

- ``usage_ledger``: daily sums per (enterprise, member, agent, model version), added when a Run ends, from the
  normalized ``usage`` of its ``model.completed`` events.
- ``usage_recorded_runs``: Runs already added, so recording is idempotent.
- ``usage_limits``: monthly token limits for the whole enterprise, one department (with everything below it) or
  one member. A Run is refused at submission while any limit that applies to its member is used up.
"""
from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import (BigInteger, CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint,
                        Uuid)
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base


class UsageLedgerRecord(Base):
    __tablename__ = 'usage_ledger'
    __table_args__ = (
        Index('ix_usage_ledger_tenant_day', 'tenant_id', 'day'),
        Index('ix_usage_ledger_user_day', 'tenant_id', 'user_id', 'day'),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False)
    day: Mapped[date] = mapped_column(Date, nullable=False)
    user_id: Mapped[UUID] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    agent_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    model_version_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    runs: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    input_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    cache_read_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    cache_creation_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)


class UsageRecordedRunRecord(Base):
    __tablename__ = 'usage_recorded_runs'

    run_id: Mapped[UUID] = mapped_column(ForeignKey('runs.id', ondelete='CASCADE'), primary_key=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class UsageLimitRecord(Base):
    __tablename__ = 'usage_limits'
    __table_args__ = (
        UniqueConstraint('tenant_id', 'scope_kind', 'scope_id', name='uq_usage_limits_scope'),
        CheckConstraint("scope_kind IN ('tenant', 'org_unit', 'user')", name='ck_usage_limits_scope'),
        CheckConstraint('monthly_tokens > 0', name='ck_usage_limits_positive'),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False)
    scope_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    #: The enterprise id for ``tenant``, a department id or a member's user id.
    scope_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    monthly_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False)
    updated_by: Mapped[UUID] = mapped_column(ForeignKey('users.id', ondelete='RESTRICT'), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
