"""Sandbox acceptance results (openspec 2026-11-07-tool-expansion 3.6, design 2.3.1).

New table `sandbox_acceptance`: the latest isolation acceptance of each sandbox profile, so an API and a worker on
different hosts agree on whether the sandbox group is available.
"""
from alembic import op
import sqlalchemy as sa

revision = 'd3e4f5a6b7c8'
down_revision = 'c2d3e4f5a6b7'
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        'sandbox_acceptance',
        sa.Column('profile', sa.String(64), primary_key=True),
        sa.Column('backend', sa.String(16), nullable=False),
        sa.Column('fingerprint', sa.String(64), nullable=False),
        sa.Column('passed', sa.Boolean(), nullable=False),
        sa.Column('items', sa.JSON(), nullable=False),
        sa.Column('checked_at', sa.DateTime(timezone=True), nullable=False),
    )


def downgrade():
    op.drop_table('sandbox_acceptance')
