"""Knowledge base shares into shared spaces (openspec 2026-11-06-knowledge-base K1.9a).

New table `knowledge_base_shares`; the tenant-level resource grants for knowledge bases keep working underneath.
"""
from alembic import op
import sqlalchemy as sa

revision = 'b1c2d3e4f5a6'
down_revision = '1a2b3c4d5e6f'
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        'knowledge_base_shares',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('tenant_id', sa.Uuid(), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('kb_id', sa.Uuid(), sa.ForeignKey('knowledge_bases.id', ondelete='CASCADE'), nullable=False),
        sa.Column('shared_space_id', sa.Uuid(), sa.ForeignKey('shared_spaces.id', ondelete='CASCADE'), nullable=False),
        sa.Column('level', sa.String(16), nullable=False),
        sa.Column('created_by', sa.Uuid(), sa.ForeignKey('users.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('kb_id', 'shared_space_id', name='uq_kb_shares_kb_space'),
        sa.CheckConstraint("level IN ('viewer', 'editor', 'admin')", name='ck_kb_shares_level'),
    )
    op.create_index('ix_kb_shares_space', 'knowledge_base_shares', ['shared_space_id'])


def downgrade():
    op.drop_index('ix_kb_shares_space', table_name='knowledge_base_shares')
    op.drop_table('knowledge_base_shares')
