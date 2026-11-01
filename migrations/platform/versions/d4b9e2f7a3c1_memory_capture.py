"""Automatic memory capture tables (openspec 2026-11-01-memory-optimization, stage 3).

Settings default to disabled and are created only when an owner changes them. Cursors and jobs
are created by capture; nothing is backfilled for existing sessions.
"""
from alembic import op
import sqlalchemy as sa

revision = 'd4b9e2f7a3c1'
down_revision = 'c3f8a1e6d2b9'
branch_labels = depends_on = None


def upgrade():
    op.create_table('memory_capture_settings',
        sa.Column('tenant_id', sa.Uuid(), sa.ForeignKey('tenants.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('owner_user_id', sa.Uuid(), sa.ForeignKey('users.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.text('0')),
        sa.Column('model_profile_version_id', sa.Uuid()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False))
    op.create_table('memory_capture_cursors',
        sa.Column('session_id', sa.Uuid(), sa.ForeignKey('sessions.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('tenant_id', sa.Uuid(), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('owner_user_id', sa.Uuid(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('last_processed_sequence', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False))
    op.create_table('memory_capture_jobs',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('tenant_id', sa.Uuid(), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('owner_user_id', sa.Uuid(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('session_id', sa.Uuid(), sa.ForeignKey('sessions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('source_run_id', sa.Uuid(), sa.ForeignKey('runs.id', ondelete='CASCADE'), nullable=False),
        sa.Column('from_sequence', sa.Integer(), nullable=False),
        sa.Column('through_sequence', sa.Integer(), nullable=False),
        sa.Column('state', sa.String(16), nullable=False),
        sa.Column('available_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('attempt_count', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('next_retry_at', sa.DateTime(timezone=True)),
        sa.Column('lease_owner', sa.String(128)),
        sa.Column('lease_expires_at', sa.DateTime(timezone=True)),
        sa.Column('last_error', sa.String(500)),
        sa.Column('actions', sa.JSON()),
        sa.Column('stored_count', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True)),
        sa.CheckConstraint("state IN ('pending','extracted','stored','completed','failed')",
                           name='ck_memory_capture_jobs_state'))
    op.create_index('ix_memory_capture_jobs_owner_state', 'memory_capture_jobs',
                    ['tenant_id', 'owner_user_id', 'state'])


def downgrade():
    op.drop_index('ix_memory_capture_jobs_owner_state', table_name='memory_capture_jobs')
    op.drop_table('memory_capture_jobs')
    op.drop_table('memory_capture_cursors')
    op.drop_table('memory_capture_settings')
