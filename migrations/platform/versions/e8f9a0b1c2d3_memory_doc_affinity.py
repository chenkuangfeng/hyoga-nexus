"""Document affinity of a person's cited knowledge documents (openspec 2026-11-06-memory-evolution D5).

Revision ID: e8f9a0b1c2d3
Revises: f9a0b1c2d3e4
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'e8f9a0b1c2d3'
down_revision: Union[str, None] = 'f9a0b1c2d3e4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('memory_doc_affinity',
        sa.Column('tenant_id', sa.Uuid(), sa.ForeignKey('tenants.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('owner_user_id', sa.Uuid(), sa.ForeignKey('users.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('document_id', sa.Uuid(), primary_key=True),
        sa.Column('hits', sa.Integer(), server_default='0', nullable=False),
        sa.Column('last_cited_at', sa.DateTime(timezone=True), nullable=False))


def downgrade() -> None:
    op.drop_table('memory_doc_affinity')
