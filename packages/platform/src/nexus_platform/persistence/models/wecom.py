"""WeCom (企业微信) self-built apps per enterprise (openspec 2026-11-11-enterprise-saas E3, decision 5).

- ``tenant_wecom_corps``: the one WeCom corp an enterprise is bound to, its callback credentials and sync status.
- ``tenant_wecom_apps``: any number of self-built apps of that corp, each with a purpose: ``workspace`` (employee
  workspace), ``admin`` (enterprise admin console) or ``agent`` (one agent's chat). One app may be marked for QR
  sign-in and is also the app whose secret reads the directory.
- ``wecom_members``: the members last read from the directory, so that a member can be given an account the first
  time they open an app, and so that departures can be detected.

Secrets are Fernet-encrypted with the deployment key (``models.provider_settings.cipher``) and never returned.
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (JSON, Boolean, CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint, Index, String, Text,
                        UniqueConstraint, Uuid, false, text)
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base


class WeComCorpRecord(Base):
    __tablename__ = 'tenant_wecom_corps'

    tenant_id: Mapped[UUID] = mapped_column(ForeignKey('tenants.id', ondelete='CASCADE'), primary_key=True)
    #: A WeCom corp can serve one enterprise only, so sign-in can find the enterprise from the corp.
    corp_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    callback_token_ciphertext: Mapped[str | None] = mapped_column(Text)
    encoding_aes_key_ciphertext: Mapped[str | None] = mapped_column(Text)
    #: ``never``, ``ok``, ``failed`` or ``requested`` (a callback asked for a fresh sync).
    sync_status: Mapped[str] = mapped_column(String(16), nullable=False, default='never', server_default='never')
    sync_error: Mapped[str | None] = mapped_column(String(500))
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_by: Mapped[UUID | None] = mapped_column(ForeignKey('users.id', ondelete='SET NULL'))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class WeComAppRecord(Base):
    __tablename__ = 'tenant_wecom_apps'
    __table_args__ = (
        UniqueConstraint('tenant_id', 'wecom_agentid', name='uq_wecom_apps_agentid'),
        CheckConstraint("purpose IN ('workspace', 'admin', 'agent')", name='ck_wecom_apps_purpose'),
        CheckConstraint("(purpose = 'agent') = (nexus_agent_id IS NOT NULL)", name='ck_wecom_apps_agent'),
        CheckConstraint("status IN ('active', 'disabled')", name='ck_wecom_apps_status'),
        ForeignKeyConstraint(['nexus_agent_id', 'tenant_id'], ['agents.id', 'agents.tenant_id'],
                             ondelete='CASCADE', name='fk_wecom_apps_agent_tenant'),
        # One agent has at most one WeCom app; at most one app per enterprise signs in by QR code.
        Index('uq_wecom_apps_agent', 'nexus_agent_id', unique=True,
              sqlite_where=text('nexus_agent_id IS NOT NULL'), postgresql_where=text('nexus_agent_id IS NOT NULL')),
        Index('uq_wecom_apps_qr', 'tenant_id', unique=True,
              sqlite_where=text('qr_login'), postgresql_where=text('qr_login')),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey('tenant_wecom_corps.tenant_id', ondelete='CASCADE'),
                                            nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    #: The WeCom app's ``AgentId`` (not a Nexus agent).
    wecom_agentid: Mapped[str] = mapped_column(String(32), nullable=False)
    secret_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    purpose: Mapped[str] = mapped_column(String(16), nullable=False)
    nexus_agent_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    qr_login: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    status: Mapped[str] = mapped_column(String(16), nullable=False, default='active', server_default='active')
    created_by: Mapped[UUID] = mapped_column(ForeignKey('users.id', ondelete='RESTRICT'), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class WeComMemberRecord(Base):
    __tablename__ = 'wecom_members'
    __table_args__ = (Index('ix_wecom_members_user', 'tenant_id', 'user_id'),)

    tenant_id: Mapped[UUID] = mapped_column(ForeignKey('tenants.id', ondelete='CASCADE'), primary_key=True)
    userid: Mapped[str] = mapped_column(String(64), primary_key=True)
    #: The Nexus account, once the member has opened an app (or was bound before the sync).
    user_id: Mapped[UUID | None] = mapped_column(ForeignKey('users.id', ondelete='SET NULL'))
    name: Mapped[str] = mapped_column(String(160), nullable=False, default='')
    department_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
