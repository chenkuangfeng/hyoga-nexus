"""Knowledge organization (openspec 2026-11-06-knowledge-base K5): tags, folders, metadata, pinning.

Revision ID: a4b5c6d7e8f9
Revises: f3a4b5c6d7e8
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'a4b5c6d7e8f9'
down_revision: Union[str, None] = 'f3a4b5c6d7e8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('knowledge_tags',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('tenant_id', sa.Uuid(), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('kb_id', sa.Uuid(), sa.ForeignKey('knowledge_bases.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(120), nullable=False),
        sa.Column('color', sa.String(32), nullable=False),
        sa.Column('sort_order', sa.Integer(), nullable=False),
        sa.Column('created_by', sa.Uuid(), sa.ForeignKey('users.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('kb_id', 'name', name='uq_knowledge_tags_name'))
    with op.batch_alter_table('knowledge_bases') as batch:
        batch.add_column(sa.Column('pinned', sa.Boolean(), server_default=sa.false(), nullable=False))
        batch.add_column(sa.Column('pinned_at', sa.DateTime(timezone=True), nullable=True))
    with op.batch_alter_table('knowledge_documents') as batch:
        batch.add_column(sa.Column('tag_ids', sa.JSON(), server_default='[]', nullable=False))
        batch.add_column(sa.Column('folder_path', sa.String(1024), server_default='', nullable=False))
        batch.add_column(sa.Column('custom_metadata', sa.JSON(), server_default='{}', nullable=False))
    with op.batch_alter_table('knowledge_faq_entries') as batch:
        batch.add_column(sa.Column('tag_id', sa.Uuid(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('knowledge_faq_entries') as batch:
        batch.drop_column('tag_id')
    with op.batch_alter_table('knowledge_documents') as batch:
        batch.drop_column('custom_metadata')
        batch.drop_column('folder_path')
        batch.drop_column('tag_ids')
    with op.batch_alter_table('knowledge_bases') as batch:
        batch.drop_column('pinned_at')
        batch.drop_column('pinned')
    op.drop_table('knowledge_tags')
