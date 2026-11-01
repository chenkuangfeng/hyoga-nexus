"""SQLAlchemy mapping for externalized tool output (P2); rows are Run-scoped and never shared across Runs."""
from __future__ import annotations
from datetime import datetime
from uuid import UUID
from sqlalchemy import DateTime, ForeignKey, Index, Integer, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column
from ..base import Base


class ToolOutputRecord(Base):
    """Full text of one tool result that was too large to keep inline.

    The id is the handle the model sees (`artifact:<id>`). Reads are authorized against `run_id`
    at read time, so a row is only reachable from the Run that produced it.
    """
    __tablename__ = 'tool_outputs'
    __table_args__ = (Index('ix_tool_outputs_run', 'run_id'),)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    run_id: Mapped[UUID] = mapped_column(ForeignKey('runs.id', ondelete='CASCADE'), nullable=False)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False)
    invocation_id: Mapped[UUID] = mapped_column(ForeignKey('tool_invocations.id', ondelete='CASCADE'), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    size_chars: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
