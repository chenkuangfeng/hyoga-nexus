"""Memory evolution stage 5: semantic recall and capture usage (openspec 2026-11-06-memory-evolution, task 5.1).

Additive only. `memory_embeddings` keeps one vector per published version and embedding model (JSON floats,
compared in process, decision 5); the space chooses the embedding model; capture jobs record token usage.
"""
from alembic import op
import sqlalchemy as sa

revision = 'f1a2b3c4d5e6'
down_revision = 'e8f4c6b1d3a5'
branch_labels = depends_on = None


def upgrade():
    op.create_table('memory_embeddings',
        sa.Column('entry_id', sa.Uuid(), sa.ForeignKey('memory_entries.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('version', sa.Integer(), primary_key=True),
        sa.Column('model_version_id', sa.Uuid(), primary_key=True),
        sa.Column('tenant_id', sa.Uuid(), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('owner_user_id', sa.Uuid(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('dims', sa.Integer(), nullable=False),
        sa.Column('vector', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False))
    op.create_index('ix_memory_embeddings_owner_model', 'memory_embeddings',
                    ['tenant_id', 'owner_user_id', 'model_version_id'])
    with op.batch_alter_table('memory_space_settings') as batch:
        batch.add_column(sa.Column('embedding_model_version_id', sa.Uuid(), nullable=True))
    with op.batch_alter_table('memory_capture_jobs') as batch:
        batch.add_column(sa.Column('usage', sa.JSON(), nullable=True))


def downgrade():
    with op.batch_alter_table('memory_capture_jobs') as batch:
        batch.drop_column('usage')
    with op.batch_alter_table('memory_space_settings') as batch:
        batch.drop_column('embedding_model_version_id')
    op.drop_index('ix_memory_embeddings_owner_model', table_name='memory_embeddings')
    op.drop_table('memory_embeddings')
