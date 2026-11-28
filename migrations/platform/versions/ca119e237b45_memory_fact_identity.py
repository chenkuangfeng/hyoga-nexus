"""Store explicit fact identity and update intent for memory proposals.

Revision ID: ca119e237b45
Revises: b7c8d9e0f1a2
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'ca119e237b45'
down_revision: Union[str, None] = 'b7c8d9e0f1a2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('memory_drafts', sa.Column('fact_identity', sa.JSON(), nullable=True))
    op.add_column('memory_drafts', sa.Column('intent', sa.String(length=16), nullable=False, server_default='add'))
    op.add_column('memory_entries', sa.Column('fact_identity', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('memory_entries', 'fact_identity')
    op.drop_column('memory_drafts', 'intent')
    op.drop_column('memory_drafts', 'fact_identity')
