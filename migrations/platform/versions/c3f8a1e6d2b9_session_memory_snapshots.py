"""Per-session memory index snapshots (openspec 2026-11-01-memory-optimization, stage 2).

Existing sessions have no snapshot; the first Run after upgrade creates one. Nothing is backfilled.
"""
from alembic import op
import sqlalchemy as sa

revision = 'c3f8a1e6d2b9'
down_revision = 'e2b7d4a8c1f6'
branch_labels = depends_on = None


def upgrade():
    op.create_table('session_memory_snapshots',
        sa.Column('session_id', sa.Uuid(), sa.ForeignKey('sessions.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('tenant_id', sa.Uuid(), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('owner_user_id', sa.Uuid(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('index_text', sa.Text(), nullable=False),
        sa.Column('version_key', sa.String(64), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False))


def downgrade():
    op.drop_table('session_memory_snapshots')
