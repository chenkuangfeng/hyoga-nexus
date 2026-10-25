"""Native candidates, user behavior settings, steer and reviewed memory versions."""
from alembic import op
import sqlalchemy as sa
revision = 'd9e351bc2802'
down_revision = 'c8d240ab1701'
branch_labels = depends_on = None


def upgrade():
    op.add_column('run_input_requests', sa.Column('candidates', sa.JSON(), nullable=False, server_default='[]'))
    op.create_table('action_approvals',
        sa.Column('id', sa.Uuid(), primary_key=True), sa.Column('run_id', sa.Uuid(), sa.ForeignKey('runs.id'), nullable=False),
        sa.Column('tool_call_id', sa.String(255), nullable=False), sa.Column('tool_name', sa.String(64), nullable=False),
        sa.Column('arguments', sa.Text(), nullable=False), sa.Column('modified_arguments', sa.Text()),
        sa.Column('binding_hash', sa.String(64), nullable=False), sa.Column('status', sa.String(16), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False), sa.Column('resolved_at', sa.DateTime(timezone=True)),
        sa.Column('consumed_at', sa.DateTime(timezone=True)), sa.UniqueConstraint('run_id','tool_call_id',name='uq_action_approval_call'))
    op.create_table('context_summaries',
        sa.Column('session_id', sa.Uuid(), sa.ForeignKey('sessions.id'), primary_key=True),
        sa.Column('workspace_id', sa.Uuid(), sa.ForeignKey('workspaces.id'), nullable=False),
        sa.Column('source_run_id', sa.Uuid(), sa.ForeignKey('runs.id'), nullable=False),
        sa.Column('through_sequence', sa.Integer(), nullable=False), sa.Column('content', sa.Text(), nullable=False))
    op.create_table('native_preferences',
        sa.Column('workspace_id', sa.Uuid(), sa.ForeignKey('workspaces.id'), primary_key=True),
        sa.Column('user_id', sa.Uuid(), sa.ForeignKey('users.id'), primary_key=True),
        sa.Column('version', sa.Integer(), nullable=False), sa.Column('settings', sa.JSON(), nullable=False))
    op.create_table('run_directives',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('run_id', sa.Uuid(), sa.ForeignKey('runs.id'), nullable=False),
        sa.Column('principal_id', sa.Uuid(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('idempotency_key', sa.String(255), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('consumed_at', sa.DateTime(timezone=True)),
        sa.UniqueConstraint('run_id', 'idempotency_key', name='uq_run_directive_key'))
    op.create_table('memory_entries',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('workspace_id', sa.Uuid(), sa.ForeignKey('workspaces.id'), nullable=False),
        sa.Column('owner_user_id', sa.Uuid(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('kind', sa.String(16), nullable=False), sa.Column('title', sa.String(160), nullable=False),
        sa.Column('project', sa.String(160), nullable=False), sa.Column('active', sa.Boolean(), nullable=False),
        sa.Column('current_version', sa.Integer(), nullable=False), sa.Column('created_at', sa.DateTime(timezone=True), nullable=False))
    op.create_table('memory_versions',
        sa.Column('entry_id', sa.Uuid(), sa.ForeignKey('memory_entries.id'), primary_key=True),
        sa.Column('version', sa.Integer(), primary_key=True), sa.Column('content', sa.Text(), nullable=False),
        sa.Column('source_run_id', sa.Uuid(), sa.ForeignKey('runs.id'), nullable=False),
        sa.Column('source_draft_id', sa.Uuid(), sa.ForeignKey('memory_drafts.id'), nullable=False),
        sa.Column('reviewed_by', sa.Uuid(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False))


def downgrade():
    for table in ('action_approvals', 'memory_versions', 'memory_entries', 'run_directives', 'native_preferences', 'context_summaries'):
        op.drop_table(table)
    op.drop_column('run_input_requests', 'candidates')
