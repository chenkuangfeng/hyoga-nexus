"""Memory evolution stage 1: capture quality (openspec 2026-11-06-memory-evolution, task 1.1).

Additive only. Drafts gain extraction metadata (topic, importance, confidence, validity end, evidence,
review annotations, target entry); entries gain topic and importance; tombstones gain the rejected
topic and an owner/time index. Existing rows keep NULL / default values: importance 3, empty topic.
"""
from alembic import op
import sqlalchemy as sa

revision = 'c4d9e2a7f1b3'
down_revision = 'a3c8e5f1d2b7'
branch_labels = depends_on = None


def upgrade():
    with op.batch_alter_table('memory_drafts') as batch:
        batch.add_column(sa.Column('topic', sa.String(160), nullable=True))
        batch.add_column(sa.Column('importance', sa.Integer(), nullable=True))
        batch.add_column(sa.Column('confidence', sa.String(8), nullable=True))
        batch.add_column(sa.Column('valid_until', sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column('evidence', sa.JSON(), nullable=True))
        batch.add_column(sa.Column('annotations', sa.JSON(), nullable=True))
        batch.add_column(sa.Column('target_entry_id', sa.Uuid(), nullable=True))
    with op.batch_alter_table('memory_entries') as batch:
        batch.add_column(sa.Column('topic', sa.String(160), nullable=False, server_default=''))
        batch.add_column(sa.Column('importance', sa.Integer(), nullable=False, server_default='3'))
    with op.batch_alter_table('memory_tombstones') as batch:
        batch.add_column(sa.Column('topic', sa.String(160), nullable=False, server_default=''))
    op.create_index('ix_memory_tombstones_owner_created', 'memory_tombstones',
                    ['tenant_id', 'owner_user_id', 'created_at'])


def downgrade():
    op.drop_index('ix_memory_tombstones_owner_created', table_name='memory_tombstones')
    with op.batch_alter_table('memory_tombstones') as batch:
        batch.drop_column('topic')
    with op.batch_alter_table('memory_entries') as batch:
        batch.drop_column('importance')
        batch.drop_column('topic')
    with op.batch_alter_table('memory_drafts') as batch:
        for column in ('target_entry_id', 'annotations', 'evidence', 'valid_until', 'confidence',
                       'importance', 'topic'):
            batch.drop_column(column)
