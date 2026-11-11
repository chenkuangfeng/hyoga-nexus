"""SQLAlchemy mapping for sandbox artifacts (openspec 2026-11-07-tool-expansion 4.6, design 2.6)."""
from __future__ import annotations
from datetime import datetime
from uuid import UUID
from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column
from ..base import Base


class ArtifactRecord(Base):
    """A file a Run left under `/outputs`, copied when the Run ended.

    The bytes live outside the database under the artifact root (`storage_key` is relative to it), so the row is
    metadata and the authorization anchor: a person reaches an artifact through the session it belongs to.
    `deleted_at` marks a removed artifact; its copy is deleted too.
    """
    __tablename__ = 'artifacts'
    __table_args__ = (
        UniqueConstraint('run_id', 'path', name='uq_artifacts_run_path'),
        Index('ix_artifacts_session', 'tenant_id', 'session_id', 'created_at'),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False)
    session_id: Mapped[UUID] = mapped_column(ForeignKey('sessions.id', ondelete='CASCADE'), nullable=False)
    run_id: Mapped[UUID] = mapped_column(ForeignKey('runs.id', ondelete='CASCADE'), nullable=False)
    owner_user_id: Mapped[UUID] = mapped_column(ForeignKey('users.id', ondelete='RESTRICT'), nullable=False)
    path: Mapped[str] = mapped_column(String(1024), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    mime: Mapped[str] = mapped_column(String(127), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
