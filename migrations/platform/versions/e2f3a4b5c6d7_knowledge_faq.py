"""FAQ entries of FAQ knowledge bases (openspec 2026-11-06-knowledge-base K3).

Revision ID: e2f3a4b5c6d7
Revises: d1e2f3a4b5c6
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e2f3a4b5c6d7'
down_revision: Union[str, None] = 'd1e2f3a4b5c6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('knowledge_faq_entries',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('kb_id', sa.Uuid(), nullable=False),
    sa.Column('category', sa.String(length=160), nullable=False),
    sa.Column('standard_question', sa.Text(), nullable=False),
    sa.Column('question_key', sa.String(length=255), nullable=False),
    sa.Column('similar_questions', sa.JSON(), nullable=False),
    sa.Column('negative_questions', sa.JSON(), nullable=False),
    sa.Column('answers', sa.JSON(), nullable=False),
    sa.Column('answer_strategy', sa.String(length=16), nullable=False),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('recommended', sa.Boolean(), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('index_state', sa.String(length=16), nullable=False),
    sa.Column('index_attempts', sa.Integer(), nullable=False),
    sa.Column('index_error', sa.Text(), nullable=True),
    sa.Column('created_by', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("index_state IN ('pending','ready','failed')", name='ck_faq_entries_index_state'),
    sa.CheckConstraint("status IN ('active','deleting')", name='ck_faq_entries_status'),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['kb_id'], ['knowledge_bases.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_faq_entries_kb', 'knowledge_faq_entries', ['kb_id', 'status', 'enabled'], unique=False)
    op.create_index('ix_faq_entries_pending', 'knowledge_faq_entries', ['index_state', 'status'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_faq_entries_pending', table_name='knowledge_faq_entries')
    op.drop_index('ix_faq_entries_kb', table_name='knowledge_faq_entries')
    op.drop_table('knowledge_faq_entries')
