"""Capacity policy for automatic capture (openspec 2026-11-01-memory-optimization, stage 3.9).

`reject` (default) refuses a capture draft when the owner's memory budget is full. `evict_auto`
archives the owner's oldest capture-origin entries to make room; hand-written entries are never evicted.
"""
from alembic import op
import sqlalchemy as sa

revision = 'e6d1a7b3c8f2'
down_revision = 'd4b9e2f7a3c1'
branch_labels = depends_on = None


def upgrade():
    with op.batch_alter_table('memory_capture_settings') as batch:
        batch.add_column(sa.Column('capacity_policy', sa.String(16), nullable=False,
                                   server_default='reject'))
        batch.create_check_constraint('ck_memory_capture_settings_capacity',
                                      "capacity_policy IN ('reject','evict_auto')")


def downgrade():
    with op.batch_alter_table('memory_capture_settings') as batch:
        batch.drop_constraint('ck_memory_capture_settings_capacity', type_='check')
        batch.drop_column('capacity_policy')
