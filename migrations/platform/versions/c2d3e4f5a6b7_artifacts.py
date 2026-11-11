"""Sandbox artifacts (openspec 2026-11-07-tool-expansion 4.6).

New table `artifacts`: metadata of files collected from `/outputs` when a Run ends; the bytes stay on disk.
"""
from alembic import op
import sqlalchemy as sa

revision = 'c2d3e4f5a6b7'
down_revision = 'b1c2d3e4f5a6'
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        'artifacts',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('tenant_id', sa.Uuid(), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('session_id', sa.Uuid(), sa.ForeignKey('sessions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('run_id', sa.Uuid(), sa.ForeignKey('runs.id', ondelete='CASCADE'), nullable=False),
        sa.Column('owner_user_id', sa.Uuid(), sa.ForeignKey('users.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('path', sa.String(1024), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('size', sa.BigInteger(), nullable=False),
        sa.Column('sha256', sa.String(64), nullable=False),
        sa.Column('mime', sa.String(127), nullable=False),
        sa.Column('storage_key', sa.String(255), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint('run_id', 'path', name='uq_artifacts_run_path'),
    )
    op.create_index('ix_artifacts_session', 'artifacts', ['tenant_id', 'session_id', 'created_at'])


def downgrade():
    op.drop_index('ix_artifacts_session', table_name='artifacts')
    op.drop_table('artifacts')
