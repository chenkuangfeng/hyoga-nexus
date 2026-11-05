"""Long-term memory switches (openspec 2026-11-05-memory-switches, task 1.1).

Additive only: a space settings table and the member's own switch on `memory_capture_settings`.
No rows are backfilled; a missing space row or member row means memory is on, so behavior is unchanged
until someone turns a switch off.
"""
from alembic import op
import sqlalchemy as sa

revision = 'a3c8e5f1d2b7'
down_revision = 'e5a1c9d3b7f2'
branch_labels = depends_on = None


def upgrade():
    op.create_table('memory_space_settings',
        sa.Column('tenant_id', sa.Uuid(), sa.ForeignKey('tenants.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('write_mode', sa.String(16), nullable=False, server_default='auto'),
        sa.Column('updated_by', sa.Uuid(), sa.ForeignKey('users.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("write_mode IN ('explicit','auto')", name='ck_memory_space_settings_write_mode'))
    with op.batch_alter_table('memory_capture_settings') as batch:
        batch.add_column(sa.Column('memory_enabled', sa.Boolean(), nullable=False, server_default=sa.true()))


def downgrade():
    with op.batch_alter_table('memory_capture_settings') as batch:
        batch.drop_column('memory_enabled')
    op.drop_table('memory_space_settings')
