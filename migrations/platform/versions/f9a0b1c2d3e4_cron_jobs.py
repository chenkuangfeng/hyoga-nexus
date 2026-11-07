"""Scheduled agent runs (openspec 2026-11-07-tool-expansion, section 8.2).

Revision ID: f9a0b1c2d3e4
Revises: d7e8f9a0b1c2
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'f9a0b1c2d3e4'
down_revision: Union[str, None] = 'd7e8f9a0b1c2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('cron_jobs',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('tenant_id', sa.Uuid(), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('owner_user_id', sa.Uuid(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('agent_version_id', sa.Uuid(), nullable=False),
        sa.Column('session_id', sa.Uuid(), sa.ForeignKey('sessions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(120), nullable=False),
        sa.Column('prompt', sa.Text(), nullable=False),
        sa.Column('rule', sa.JSON(), nullable=False),
        sa.Column('timezone', sa.String(64), nullable=False),
        sa.Column('state', sa.String(16), nullable=False, server_default='active'),
        sa.Column('next_run_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_run_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_run_id', sa.Uuid(), nullable=True),
        sa.Column('last_error', sa.String(120), nullable=False, server_default=''),
        sa.Column('run_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('session_id', name='uq_cron_jobs_session'))
    op.create_index('ix_cron_jobs_due', 'cron_jobs', ['state', 'next_run_at'])
    op.create_index('ix_cron_jobs_owner', 'cron_jobs', ['tenant_id', 'owner_user_id'])


def downgrade() -> None:
    op.drop_index('ix_cron_jobs_owner', table_name='cron_jobs')
    op.drop_index('ix_cron_jobs_due', table_name='cron_jobs')
    op.drop_table('cron_jobs')
