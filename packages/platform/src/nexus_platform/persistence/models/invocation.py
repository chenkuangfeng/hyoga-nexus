"""SQLAlchemy invocation mappings; domain-owned tables with their existing columns and constraints."""
from __future__ import annotations
from datetime import datetime
from typing import Any
from uuid import UUID
from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column
from ..base import Base


class ToolInvocationRecord(Base):
    __tablename__ = "tool_invocations"
    __table_args__ = (Index("uq_tool_invocations_operation", "run_id", "operation_id", unique=True),)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), nullable=False)
    resource_binding_id: Mapped[UUID | None] = mapped_column(ForeignKey("agent_resource_bindings.id", ondelete="SET NULL"))
    operation_id: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    input_summary: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    output_summary: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    error_code: Mapped[str | None] = mapped_column(String(80))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
