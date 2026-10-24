"""Native messages, progress, input, checkpoint and draft storage.

Revision ID: b5a16ed22801
Revises: 9608e45573e5
"""
from alembic import op
import sqlalchemy as sa

revision = 'b5a16ed22801'
down_revision = '9608e45573e5'
branch_labels = depends_on = None


def upgrade():
    op.add_column('messages', sa.Column('runtime_metadata', sa.JSON(), nullable=False, server_default='{}'))
    op.create_index('uq_runs_active_session', 'runs', ['session_id'], unique=True,
                    sqlite_where=sa.text("status IN ('queued','running','waiting_input','waiting_approval')"),
                    postgresql_where=sa.text("status IN ('queued','running','waiting_input','waiting_approval')"))
    op.create_index('uq_tool_invocations_operation', 'tool_invocations', ['run_id', 'operation_id'], unique=True)
    op.create_table('native_run_states',
        sa.Column('run_id', sa.Uuid(), sa.ForeignKey('runs.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('progress', sa.JSON(), nullable=False))
    op.create_table('run_input_requests',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('run_id', sa.Uuid(), sa.ForeignKey('runs.id', ondelete='CASCADE'), nullable=False),
        sa.Column('question', sa.Text(), nullable=False), sa.Column('response', sa.Text()),
        sa.Column('response_key', sa.String(255)), sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('responded_at', sa.DateTime(timezone=True)),
        sa.UniqueConstraint('run_id', 'response_key', name='uq_input_response_key'))
    op.create_table('session_checkpoints',
        sa.Column('session_id', sa.Uuid(), sa.ForeignKey('sessions.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('workspace_id', sa.Uuid(), sa.ForeignKey('workspaces.id', ondelete='CASCADE'), nullable=False),
        sa.Column('source_run_id', sa.Uuid(), sa.ForeignKey('runs.id', ondelete='CASCADE'), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False))
    op.create_table('memory_drafts',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('workspace_id', sa.Uuid(), sa.ForeignKey('workspaces.id', ondelete='CASCADE'), nullable=False),
        sa.Column('source_run_id', sa.Uuid(), sa.ForeignKey('runs.id', ondelete='CASCADE'), nullable=False),
        sa.Column('kind', sa.String(16), nullable=False), sa.Column('scope', sa.String(255), nullable=False),
        sa.Column('diff', sa.Text(), nullable=False), sa.Column('status', sa.String(24), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False))


def downgrade():
    for table in ('memory_drafts', 'session_checkpoints', 'run_input_requests', 'native_run_states'):
        op.drop_table(table)
    op.drop_index('uq_tool_invocations_operation', table_name='tool_invocations')
    op.drop_index('uq_runs_active_session', table_name='runs')
    op.drop_column('messages', 'runtime_metadata')
