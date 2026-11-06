"""Memory evolution stage 3: consolidation scheduling (openspec 2026-11-06-memory-evolution, task 3.1).

One row per owner and space records when consolidation last ran, when the owner last asked for it,
whether a requested pass is waiting, and which worker holds it. Merge drafts reuse `memory_drafts`
(origin `background`, `annotations.merge`), so no draft column changes.
"""
from alembic import op
import sqlalchemy as sa

revision = 'e8f4c6b1d3a5'
down_revision = 'd7e3b5a9c2f4'
branch_labels = depends_on = None


def upgrade():
    op.create_table('memory_consolidation_state',
        sa.Column('tenant_id', sa.Uuid(), sa.ForeignKey('tenants.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('owner_user_id', sa.Uuid(), sa.ForeignKey('users.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('last_run_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_forced_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('requested_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('lease_owner', sa.String(255), nullable=True),
        sa.Column('lease_until', sa.DateTime(timezone=True), nullable=True))


def downgrade():
    op.drop_table('memory_consolidation_state')
