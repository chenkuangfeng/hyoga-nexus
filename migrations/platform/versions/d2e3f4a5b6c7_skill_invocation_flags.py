"""Skill invocation flags and declared execution place (openspec 2026-11-07-skill-evolution, S1).

Revision ID: d2e3f4a5b6c7
Revises: c1d2e3f4a5b6
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'd2e3f4a5b6c7'
down_revision: Union[str, None] = 'c1d2e3f4a5b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('skill_versions') as batch:
        batch.add_column(sa.Column('model_invocable', sa.Boolean(), nullable=False, server_default=sa.true()))
        batch.add_column(sa.Column('user_invocable', sa.Boolean(), nullable=False, server_default=sa.true()))
        batch.add_column(sa.Column('execution', sa.String(16), nullable=False, server_default='sandbox'))


def downgrade() -> None:
    with op.batch_alter_table('skill_versions') as batch:
        batch.drop_column('execution')
        batch.drop_column('user_invocable')
        batch.drop_column('model_invocable')
