"""Parent-child chunks (openspec 2026-11-06-knowledge-base K4).

`knowledge_chunks.parent_id` links a child to its parent chunk; `indexed` is false for parents of a parent-child
split (stored and readable, not embedded or searched). Existing rows are ordinary chunks: no parent, indexed.

Revision ID: f3a4b5c6d7e8
Revises: e2f3a4b5c6d7
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'f3a4b5c6d7e8'
down_revision: Union[str, None] = 'e2f3a4b5c6d7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('knowledge_chunks') as batch:
        batch.add_column(sa.Column('parent_id', sa.Uuid(), nullable=True))
        batch.add_column(sa.Column('indexed', sa.Boolean(), server_default=sa.true(), nullable=False))


def downgrade() -> None:
    with op.batch_alter_table('knowledge_chunks') as batch:
        batch.drop_column('indexed')
        batch.drop_column('parent_id')
