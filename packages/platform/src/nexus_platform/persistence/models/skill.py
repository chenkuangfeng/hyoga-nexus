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

from sqlalchemy import (JSON, Boolean, DateTime, ForeignKey, Index, Integer, LargeBinary, String, Text, UniqueConstraint,
                        Uuid, text, true)
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base


class SkillRecord(Base):
    """A named skill inside one Tenant. ``current_version_id`` points at the newest published version."""

    __tablename__ = "skills"
    __table_args__ = (
        # Library skills (no owner) are unique per space; private skills are unique per owner within the space.
        Index("uq_skills_library_name", "tenant_id", "name", unique=True,
              sqlite_where=text("owner_user_id IS NULL"), postgresql_where=text("owner_user_id IS NULL")),
        Index("uq_skills_private_name", "tenant_id", "owner_user_id", "name", unique=True,
              sqlite_where=text("owner_user_id IS NOT NULL"), postgresql_where=text("owner_user_id IS NOT NULL")),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    #: ``builtin`` / ``admin`` / ``import`` / ``agent`` / ``user`` (openspec 2026-11-07-skill-evolution).
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="admin")
    current_version_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    #: Set for a private skill: only this user's Runs see it. Null for the space library and builtin skills.
    owner_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    #: A private skill the owner deleted: hidden everywhere, restorable.
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SkillVersionRecord(Base):
    """One published, immutable version. ``content_hash`` covers SKILL.md and every version file."""

    __tablename__ = "skill_versions"
    __table_args__ = (
        UniqueConstraint("skill_id", "version", name="uq_skill_versions_number"),
        # One install at a time per skill (openspec 2026-11-07-skill-evolution, S3).
        Index("uq_skill_versions_installing", "skill_id", unique=True,
              sqlite_where=text("build_state = 'installing'"), postgresql_where=text("build_state = 'installing'")),
    )

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
    #: The canonical zip of the version (``nexus_skills.bundle.pack``). Null on versions published before bundles
    #: existed; it is rebuilt from the file rows when needed. Binary files exist only here.
    bundle: Mapped[bytes | None] = mapped_column(LargeBinary)
    bundle_sha256: Mapped[str | None] = mapped_column(String(64))
    #: ``installing`` -> ``ready`` | ``failed``. A version that is not ``ready`` is never served.
    build_state: Mapped[str] = mapped_column(String(16), nullable=False, default="ready", server_default="ready")
    build_error: Mapped[str | None] = mapped_column(Text)
    #: The last lines of the dependency build, for the install page.
    build_log: Mapped[str | None] = mapped_column(Text)
    build_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: Name of the built dependency environment directory, when the skill has a dependency manifest.
    env_ref: Mapped[str | None] = mapped_column(String(200))
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


class SkillDraftRecord(Base):
    """A mutable draft a user (or the model for the user) edits before saving it as a private skill version.

    Drafts are never read by ``load_skill``; saving packs one into a zip and installs it like any upload.
    ``base_hash`` is the content hash of the version the draft was started from ('' for a new skill).
    """

    __tablename__ = "skill_drafts"

    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True)
    owner_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    name: Mapped[str] = mapped_column(String(64), primary_key=True)
    skill_md: Mapped[str] = mapped_column(Text, nullable=False)
    files: Mapped[dict[str, str]] = mapped_column(JSON, nullable=False, default=dict)
    base_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="", server_default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SkillSubmissionRecord(Base):
    """A request to put a skill into the space library, waiting for an administrator (openspec 2026-11-07-skill-evolution, S5).

    ``bundle`` is the zip as submitted, so what the reviewer reads is what gets published. ``base_hash`` is the content
    hash of the library version the submission was made against ('' for a new name): approving a submission whose base has
    moved is refused. ``published_version_id`` ties an approved submission to the library version it produced.
    """

    __tablename__ = "skill_submissions"
    __table_args__ = (Index("ix_skill_submissions_state", "tenant_id", "state", "created_at"),)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    #: ``user`` / ``agent`` / ``import``: who made the content, which decides the release policy.
    origin: Mapped[str] = mapped_column(String(16), nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    bundle: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    base_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="", server_default="")
    scan: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    #: ``pending`` / ``approved`` / ``rejected`` / ``superseded`` / ``withdrawn``.
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    submitted_by: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    reviewed_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    review_reason: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    published_version_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SkillUsageRecord(Base):
    """How often, and when last, a user's Runs used a skill (openspec 2026-11-07-skill-evolution, 6.2).

    One row per (skill, user). ``use_count`` counts ``load_skill``; running a script only refreshes ``last_used_at``.
    The library view adds the rows of a skill up and never shows who used it.
    """

    __tablename__ = "skill_usage"

    skill_id: Mapped[UUID] = mapped_column(ForeignKey("skills.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    last_used_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    use_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
