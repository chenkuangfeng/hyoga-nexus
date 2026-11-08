"""Skill usage records (openspec 2026-11-07-skill-evolution, 6.2).

Revision ID: b6c7d8e9f0a1
Revises: a5b6c7d8e9f0
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'b6c7d8e9f0a1'
down_revision: Union[str, None] = 'a5b6c7d8e9f0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'skill_usage',
        sa.Column('skill_id', sa.Uuid(), sa.ForeignKey('skills.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('user_id', sa.Uuid(), sa.ForeignKey('users.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('use_count', sa.Integer(), nullable=False, server_default='0'))


def downgrade() -> None:
    op.drop_table('skill_usage')
