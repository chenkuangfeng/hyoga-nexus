"""SQLAlchemy mapping for sandbox acceptance results (openspec 2026-11-07-tool-expansion 3.6, design 2.3.1)."""
from __future__ import annotations
from datetime import datetime
from typing import Any
from sqlalchemy import JSON, Boolean, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column
from ..base import Base


class SandboxAcceptanceRecord(Base):
    """The latest isolation acceptance of one sandbox profile, shared by the API and every worker.

    One row per profile, replaced by each new run. The result counts only while `fingerprint` equals the
    fingerprint of the profile's current backend, image and limits (`nexus_sandbox.acceptance.fingerprint`).
    """
    __tablename__ = 'sandbox_acceptance'
    profile: Mapped[str] = mapped_column(String(64), primary_key=True)
    backend: Mapped[str] = mapped_column(String(16), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    items: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
