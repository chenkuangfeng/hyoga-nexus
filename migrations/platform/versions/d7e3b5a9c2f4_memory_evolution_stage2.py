"""Memory evolution stage 2: injection and visibility (openspec 2026-11-06-memory-evolution, task 2.1).

Additive only. Entries gain usage statistics (`last_used_at`, `use_count`); the space settings gain the
custom extraction rules; session snapshots record which entries the resident profile block contains, so
each Run can report them in a `memory.used` event. The new `profile` kind needs no schema change.
"""
from alembic import op
import sqlalchemy as sa

revision = 'd7e3b5a9c2f4'
down_revision = 'c4d9e2a7f1b3'
branch_labels = depends_on = None


def upgrade():
    with op.batch_alter_table('memory_entries') as batch:
        batch.add_column(sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column('use_count', sa.Integer(), nullable=False, server_default='0'))
    with op.batch_alter_table('memory_space_settings') as batch:
        batch.add_column(sa.Column('extract_instructions', sa.Text(), nullable=False, server_default=''))
    with op.batch_alter_table('session_memory_snapshots') as batch:
        batch.add_column(sa.Column('resident_entries', sa.JSON(), nullable=True))


def downgrade():
    with op.batch_alter_table('session_memory_snapshots') as batch:
        batch.drop_column('resident_entries')
    with op.batch_alter_table('memory_space_settings') as batch:
        batch.drop_column('extract_instructions')
    with op.batch_alter_table('memory_entries') as batch:
        batch.drop_column('use_count')
        batch.drop_column('last_used_at')
