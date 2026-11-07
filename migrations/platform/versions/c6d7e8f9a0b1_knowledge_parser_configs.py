"""Parser engine connection settings per space (openspec 2026-11-06-knowledge-base K4).

Revision ID: c6d7e8f9a0b1
Revises: b5c6d7e8f9a0
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'c6d7e8f9a0b1'
down_revision: Union[str, None] = 'b5c6d7e8f9a0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('knowledge_parser_configs',
        sa.Column('tenant_id', sa.Uuid(), sa.ForeignKey('tenants.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('config', sa.JSON(), nullable=False),
        sa.Column('updated_by', sa.Uuid(), sa.ForeignKey('users.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False))


def downgrade() -> None:
    op.drop_table('knowledge_parser_configs')
