"""IM channels bound to one agent (openspec 2026-11-11-enterprise-saas E4, decision 6).

New tables ``agent_channels``, ``channel_session_bindings``, ``channel_messages`` and ``channel_deliveries``.
"""
from alembic import op
import sqlalchemy as sa

revision = 'b8c9d0e1f2a3'
down_revision = 'a7b8c9d0e1f2'
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        'agent_channels',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('tenant_id', sa.Uuid(), nullable=False),
        sa.Column('agent_id', sa.Uuid(), nullable=False),
        sa.Column('kind', sa.String(16), nullable=False),
        sa.Column('name', sa.String(80), nullable=False, server_default=''),
        sa.Column('owner_user_id', sa.Uuid(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('config_ciphertext', sa.Text()),
        sa.Column('wecom_app_id', sa.Uuid(), sa.ForeignKey('tenant_wecom_apps.id', ondelete='CASCADE')),
        sa.Column('bound_external_id', sa.String(128)),
        sa.Column('claim_code_hash', sa.String(64)),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('review_note', sa.String(500)),
        sa.Column('reviewed_by', sa.Uuid(), sa.ForeignKey('users.id', ondelete='SET NULL')),
        sa.Column('reviewed_at', sa.DateTime(timezone=True)),
        sa.Column('lease_owner', sa.String(128)),
        sa.Column('lease_until', sa.DateTime(timezone=True)),
        sa.Column('cursor', sa.Text()),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['agent_id', 'tenant_id'], ['agents.id', 'agents.tenant_id'], ondelete='CASCADE',
                                name='fk_agent_channels_agent_tenant'),
        sa.CheckConstraint("kind IN ('wecom_app', 'wecom_bot', 'wechat', 'qq')", name='ck_agent_channels_kind'),
        sa.CheckConstraint("status IN ('binding', 'pending_review', 'active', 'rejected', 'disabled', 'expired')",
                           name='ck_agent_channels_status'),
    )
    op.create_index('ix_agent_channels_agent', 'agent_channels', ['tenant_id', 'agent_id'])
    op.create_index('ix_agent_channels_status', 'agent_channels', ['kind', 'status', 'lease_until'])
    op.create_table(
        'channel_session_bindings',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('channel_id', sa.Uuid(), sa.ForeignKey('agent_channels.id', ondelete='CASCADE'), nullable=False),
        sa.Column('conversation', sa.String(255), nullable=False),
        sa.Column('user_id', sa.Uuid(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('session_id', sa.Uuid(), sa.ForeignKey('sessions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('channel_id', 'conversation', 'user_id', name='uq_channel_session'),
    )
    op.create_table(
        'channel_messages',
        sa.Column('channel_id', sa.Uuid(), sa.ForeignKey('agent_channels.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('message_id', sa.String(128), primary_key=True),
        sa.Column('received_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        'channel_deliveries',
        sa.Column('run_id', sa.Uuid(), sa.ForeignKey('runs.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('channel_id', sa.Uuid(), sa.ForeignKey('agent_channels.id', ondelete='CASCADE'), nullable=False),
        sa.Column('conversation', sa.String(255), nullable=False),
        sa.Column('recipient', sa.String(128), nullable=False),
        sa.Column('reply_context', sa.Text()),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('attempts', sa.Integer(), nullable=False),
        sa.Column('last_error', sa.String(300)),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('pending', 'sent', 'failed')", name='ck_channel_deliveries_status'),
    )
    op.create_index('ix_channel_deliveries_status', 'channel_deliveries', ['status', 'updated_at'])


def downgrade():
    op.drop_index('ix_channel_deliveries_status', table_name='channel_deliveries')
    op.drop_table('channel_deliveries')
    op.drop_table('channel_messages')
    op.drop_table('channel_session_bindings')
    op.drop_index('ix_agent_channels_status', table_name='agent_channels')
    op.drop_index('ix_agent_channels_agent', table_name='agent_channels')
    op.drop_table('agent_channels')
