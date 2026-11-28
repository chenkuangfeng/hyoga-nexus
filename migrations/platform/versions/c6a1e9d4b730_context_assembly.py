"""Track context provenance without copying transcripts.

Revision ID: c6a1e9d4b730
Revises: f2c4a6b8d0e1
"""
from alembic import op
import sqlalchemy as sa

revision = 'c6a1e9d4b730'
down_revision = 'f2c4a6b8d0e1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Legacy NULL snapshots are lazily rebuilt under current authorization."""
    op.create_table('run_context_blocks',
        sa.Column('run_id', sa.Uuid(), sa.ForeignKey('runs.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('key', sa.String(255), primary_key=True),
        sa.Column('digest', sa.String(64), nullable=False),
        sa.Column('data', sa.JSON(), nullable=False))
    op.add_column('runs', sa.Column('context_manifest', sa.JSON(), nullable=True))
    runs = sa.table('runs', sa.column('context_manifest', sa.JSON()), sa.column('status', sa.String()),
                    sa.column('attempt', sa.Integer()))
    # Executed legacy Runs have no complete provenance ledger. Retain their records for
    # authorized UI/audit, but never silently treat unknown injected sources as unrestricted.
    op.execute(runs.update().where(sa.or_(runs.c.status != 'queued', runs.c.attempt > 0)).values(
        context_manifest={'schema_version': 0, 'dependencies': []}))
    for table in ('session_memory_snapshots', 'session_skill_snapshots'):
        op.add_column(table, sa.Column('context_dependencies', sa.JSON(), nullable=True))
        op.add_column(table, sa.Column('context_schema_version', sa.Integer(), nullable=False, server_default='0'))


def downgrade() -> None:
    """Remove provenance columns while retaining original messages and snapshots."""
    op.drop_table('run_context_blocks')
    for table in ('session_skill_snapshots', 'session_memory_snapshots'):
        with op.batch_alter_table(table) as batch:
            batch.drop_column('context_dependencies')
            batch.drop_column('context_schema_version')
    with op.batch_alter_table('runs') as batch:
        batch.drop_column('context_manifest')
