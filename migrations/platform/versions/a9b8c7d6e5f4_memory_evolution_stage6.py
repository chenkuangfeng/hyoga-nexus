"""Memory evolution stage 6: interest topics and the external provider choice
(openspec 2026-11-06-memory-evolution, tasks 6.1 and 6.3).

`memory_topic_stats` counts, per owner, in how many conversations a subject came up; the space sets the
promotion threshold and may name one registered external memory provider. Additive only.
"""
from alembic import op
import sqlalchemy as sa

revision = 'a9b8c7d6e5f4'
down_revision = 'f1a2b3c4d5e6'
branch_labels = depends_on = None


def upgrade():
    op.create_table('memory_topic_stats',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('tenant_id', sa.Uuid(), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('owner_user_id', sa.Uuid(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('normalized_key', sa.String(160), nullable=False),
        sa.Column('topic', sa.String(160), nullable=False),
        sa.Column('aliases', sa.JSON(), nullable=True),
        sa.Column('session_ids', sa.JSON(), nullable=True),
        sa.Column('hits', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('promoted_at', sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint('tenant_id', 'owner_user_id', 'normalized_key', name='uq_memory_topic_stats_key'))
    with op.batch_alter_table('memory_space_settings') as batch:
        batch.add_column(sa.Column('interest_threshold', sa.Integer(), nullable=False, server_default='3'))
        batch.add_column(sa.Column('memory_provider', sa.String(64), nullable=True))


def downgrade():
    with op.batch_alter_table('memory_space_settings') as batch:
        batch.drop_column('memory_provider')
        batch.drop_column('interest_threshold')
    op.drop_table('memory_topic_stats')
