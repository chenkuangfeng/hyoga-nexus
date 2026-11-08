"""Skill submissions (openspec 2026-11-07-skill-evolution, S5 5.1).

Revision ID: a5b6c7d8e9f0
Revises: f4a5b6c7d8e9
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'a5b6c7d8e9f0'
down_revision: Union[str, None] = 'f4a5b6c7d8e9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'skill_submissions',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('tenant_id', sa.Uuid(), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('origin', sa.String(16), nullable=False),
        sa.Column('name', sa.String(64), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('bundle', sa.LargeBinary(), nullable=False),
        sa.Column('content_hash', sa.String(64), nullable=False),
        sa.Column('base_hash', sa.String(64), nullable=False, server_default=''),
        sa.Column('scan', sa.JSON(), nullable=False),
        sa.Column('state', sa.String(16), nullable=False),
        sa.Column('submitted_by', sa.Uuid(), sa.ForeignKey('users.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('reviewed_by', sa.Uuid(), sa.ForeignKey('users.id', ondelete='RESTRICT'), nullable=True),
        sa.Column('review_reason', sa.Text(), nullable=False, server_default=''),
        sa.Column('published_version_id', sa.Uuid(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True))
    op.create_index('ix_skill_submissions_state', 'skill_submissions', ['tenant_id', 'state', 'created_at'])


def downgrade() -> None:
    op.drop_index('ix_skill_submissions_state', table_name='skill_submissions')
    op.drop_table('skill_submissions')
