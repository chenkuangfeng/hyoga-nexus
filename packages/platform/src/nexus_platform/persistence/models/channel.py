"""IM channels bound to one agent (openspec 2026-11-11-enterprise-saas E4, decision 6; design section 7).

- ``agent_channels``: one channel of one agent. ``kind`` is ``wecom_app`` (messages of an agent-purpose WeCom
  self-built app), ``wecom_bot`` (WeCom smart bot), ``wechat`` (the creator's own WeChat through iLink) or ``qq``
  (the creator's own QQ bot). Credentials are sealed in ``config_ciphertext``. Long connections are held by one
  worker at a time through ``lease_owner`` / ``lease_until``; ``cursor`` keeps a long-poll position.
- ``channel_session_bindings``: which Nexus session continues one (channel, conversation, member).
- ``channel_messages``: message ids already handled, so redelivered messages run once.
- ``channel_deliveries``: the reply owed for one Run, sent by the worker when the Run stops.
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint, Index, Integer, String, Text,
                        UniqueConstraint, Uuid)
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base

CHANNEL_KINDS = ('wecom_app', 'wecom_bot', 'wechat', 'qq')
CHANNEL_STATUSES = ('binding', 'pending_review', 'active', 'rejected', 'disabled', 'expired')


class AgentChannelRecord(Base):
    __tablename__ = 'agent_channels'
    __table_args__ = (
        ForeignKeyConstraint(['agent_id', 'tenant_id'], ['agents.id', 'agents.tenant_id'], ondelete='CASCADE',
                             name='fk_agent_channels_agent_tenant'),
        CheckConstraint("kind IN ('wecom_app', 'wecom_bot', 'wechat', 'qq')", name='ck_agent_channels_kind'),
        CheckConstraint("status IN ('binding', 'pending_review', 'active', 'rejected', 'disabled', 'expired')",
                        name='ck_agent_channels_status'),
        Index('ix_agent_channels_agent', 'tenant_id', 'agent_id'),
        Index('ix_agent_channels_status', 'kind', 'status', 'lease_until'),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    agent_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False, default='')
    #: Who created the channel; for ``wechat`` and ``qq`` the only person the channel serves.
    owner_user_id: Mapped[UUID] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    config_ciphertext: Mapped[str | None] = mapped_column(Text)
    wecom_app_id: Mapped[UUID | None] = mapped_column(ForeignKey('tenant_wecom_apps.id', ondelete='CASCADE'))
    #: WeChat / QQ: the owner's id on that platform, written when binding completes.
    bound_external_id: Mapped[str | None] = mapped_column(String(128))
    claim_code_hash: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    review_note: Mapped[str | None] = mapped_column(String(500))
    reviewed_by: Mapped[UUID | None] = mapped_column(ForeignKey('users.id', ondelete='SET NULL'))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_owner: Mapped[str | None] = mapped_column(String(128))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cursor: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ChannelSessionBindingRecord(Base):
    __tablename__ = 'channel_session_bindings'
    __table_args__ = (UniqueConstraint('channel_id', 'conversation', 'user_id', name='uq_channel_session'),)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    channel_id: Mapped[UUID] = mapped_column(ForeignKey('agent_channels.id', ondelete='CASCADE'), nullable=False)
    #: The platform conversation (chat or group id; the sender's id for one-to-one chats).
    conversation: Mapped[str] = mapped_column(String(255), nullable=False)
    user_id: Mapped[UUID] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    session_id: Mapped[UUID] = mapped_column(ForeignKey('sessions.id', ondelete='CASCADE'), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ChannelMessageRecord(Base):
    __tablename__ = 'channel_messages'

    channel_id: Mapped[UUID] = mapped_column(ForeignKey('agent_channels.id', ondelete='CASCADE'), primary_key=True)
    message_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ChannelDeliveryRecord(Base):
    __tablename__ = 'channel_deliveries'
    __table_args__ = (
        CheckConstraint("status IN ('pending', 'sent', 'failed')", name='ck_channel_deliveries_status'),
        Index('ix_channel_deliveries_status', 'status', 'updated_at'),
    )

    run_id: Mapped[UUID] = mapped_column(ForeignKey('runs.id', ondelete='CASCADE'), primary_key=True)
    channel_id: Mapped[UUID] = mapped_column(ForeignKey('agent_channels.id', ondelete='CASCADE'), nullable=False)
    conversation: Mapped[str] = mapped_column(String(255), nullable=False)
    #: Where the platform sends the reply: the member's id (WeCom userid, WeChat / QQ id).
    recipient: Mapped[str] = mapped_column(String(128), nullable=False)
    #: Platform context needed to reply (for example the iLink ``context_token``).
    reply_context: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default='pending')
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
