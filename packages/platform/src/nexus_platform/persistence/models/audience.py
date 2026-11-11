"""Departments and members who may use an agent or read a knowledge base
(openspec 2026-11-11-enterprise-saas E5, decision 5).

An audience row names a member (``user``) or a department (``org_unit``); with ``include_descendants`` a department
row also covers every department below it. Agent audiences grant use (view and run) only; knowledge base audiences
grant reading of a base whose ``visibility`` is ``scoped``. Rows are evaluated against the current organization at
every check, so a move between departments takes effect on the next call.
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (Boolean, CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint, Index, String,
                        UniqueConstraint, Uuid)
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base


class AgentAudienceRecord(Base):
    __tablename__ = 'agent_audiences'
    __table_args__ = (
        ForeignKeyConstraint(['agent_id', 'tenant_id'], ['agents.id', 'agents.tenant_id'], ondelete='CASCADE',
                             name='fk_agent_audiences_agent_tenant'),
        UniqueConstraint('agent_id', 'principal_kind', 'principal_id', name='uq_agent_audiences'),
        CheckConstraint("principal_kind IN ('user', 'org_unit')", name='ck_agent_audiences_kind'),
        Index('ix_agent_audiences_principal', 'tenant_id', 'principal_kind', 'principal_id'),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    agent_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    principal_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    principal_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    include_descendants: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    granted_by: Mapped[UUID] = mapped_column(ForeignKey('users.id', ondelete='RESTRICT'), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class KnowledgeBaseAudienceRecord(Base):
    __tablename__ = 'knowledge_base_audiences'
    __table_args__ = (
        ForeignKeyConstraint(['kb_id', 'tenant_id'], ['knowledge_bases.id', 'knowledge_bases.tenant_id'],
                             ondelete='CASCADE', name='fk_kb_audiences_kb_tenant'),
        UniqueConstraint('kb_id', 'principal_kind', 'principal_id', name='uq_kb_audiences'),
        CheckConstraint("principal_kind IN ('user', 'org_unit')", name='ck_kb_audiences_kind'),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    kb_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    principal_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    principal_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    include_descendants: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    granted_by: Mapped[UUID] = mapped_column(ForeignKey('users.id', ondelete='RESTRICT'), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
