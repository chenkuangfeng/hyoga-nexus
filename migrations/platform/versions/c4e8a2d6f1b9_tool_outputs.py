"""Externalized tool output table (openspec 2026-11-01-context-token-performance, P2).

Only the full text is stored here; the model-visible tool row keeps a preview and this table's id.
Rows cascade with their Run and invocation, so retention follows the Run.
"""
from alembic import op
import sqlalchemy as sa

revision = 'c4e8a2d6f1b9'
down_revision = 'b2f6a1d8c3e5'
branch_labels = depends_on = None


def upgrade():
    op.create_table('tool_outputs',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('run_id', sa.Uuid(), sa.ForeignKey('runs.id', ondelete='CASCADE'), nullable=False),
        sa.Column('tenant_id', sa.Uuid(), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('invocation_id', sa.Uuid(), sa.ForeignKey('tool_invocations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('size_chars', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False))
    op.create_index('ix_tool_outputs_run', 'tool_outputs', ['run_id'])


def downgrade():
    op.drop_index('ix_tool_outputs_run', table_name='tool_outputs')
    op.drop_table('tool_outputs')
