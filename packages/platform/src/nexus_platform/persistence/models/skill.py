"""Skill tables: definitions, immutable versions, version files and per-session index snapshots.

A skill version is never edited after it is published. Agents bind a skill through
``agent_resource_bindings`` (kind ``skill``) whose ``resource_version_id`` names the version, and
publishing registers that version in ``platform_resources`` so the binding foreign key and
authorization checks apply unchanged.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, Uuid, true
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base


class SkillRecord(Base):
    """A named skill inside one Tenant. ``current_version_id`` points at the newest published version."""

    __tablename__ = "skills"
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_skills_tenant_name"),)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    #: ``builtin`` / ``admin`` / ``import`` / ``agent`` / ``user`` (openspec 2026-11-07-skill-evolution).
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="admin")
    current_version_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    created_by: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SkillVersionRecord(Base):
    """One published, immutable version. ``content_hash`` covers SKILL.md and every version file."""

    __tablename__ = "skill_versions"
    __table_args__ = (UniqueConstraint("skill_id", "version", name="uq_skill_versions_number"),)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    skill_id: Mapped[UUID] = mapped_column(ForeignKey("skills.id", ondelete="CASCADE"), nullable=False)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    skill_md: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    tools: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    scripts: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    scan_hints: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    #: Trust level of the source at publish time (``builtin`` / ``admin`` / ``import`` / ``agent`` / ``user``).
    trust: Mapped[str] = mapped_column(String(16), nullable=False, default="admin", server_default="admin")
    #: Version of the scanner that produced ``scan``; versions scanned by an older scanner are marked for rescan.
    scan_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    #: Structured scanner result: ``{"verdict": "safe|caution|dangerous", "findings": [...]}``.
    scan: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    #: False hides the skill from the model (not indexed, ``load_skill`` refuses it).
    model_invocable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    user_invocable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    #: Declared place for the skill's scripts: ``sandbox`` or ``local`` (builtin skills only).
    execution: Mapped[str] = mapped_column(String(16), nullable=False, default="sandbox", server_default="sandbox")
    #: Frontmatter keys this platform does not know, kept verbatim, plus parse notes such as ``frontmatter_repaired``.
    extra: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SkillVersionFileRecord(Base):
    """A resource file of one version (``refs/...``, ``scripts/...``). Content is fixed at publish time."""

    __tablename__ = "skill_version_files"

    version_id: Mapped[UUID] = mapped_column(ForeignKey("skill_versions.id", ondelete="CASCADE"), primary_key=True)
    path: Mapped[str] = mapped_column(String(200), primary_key=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)


class SessionSkillSnapshotRecord(Base):
    """The skill index shown to a session, frozen by its first Run so the system prompt stays stable."""

    __tablename__ = "session_skill_snapshots"

    session_id: Mapped[UUID] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    agent_version_id: Mapped[UUID] = mapped_column(ForeignKey("agent_versions.id", ondelete="CASCADE"), nullable=False)
    index_text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
