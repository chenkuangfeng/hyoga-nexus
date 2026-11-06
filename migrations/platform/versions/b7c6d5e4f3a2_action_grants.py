"""Session grants for tool approvals (openspec 2026-11-06-tool-call-hardening, task 5.1).

`action_grants` is the ActionGrant of architecture 2.11: an owner's standing "allow" for one tool in one
session under one agent version. Revocation is a soft delete (`revoked_at`) for the audit trail; a partial
unique index keeps one active grant per (scope, scope_id, agent version, tool). `action_approvals` gains
`reason` (`policy` or `guard`) and `risk`, which decide whether an approval may be remembered.
"""
from alembic import op
import sqlalchemy as sa

revision = 'b7c6d5e4f3a2'
down_revision = 'a9b8c7d6e5f4'
branch_labels = depends_on = None


def upgrade():
    op.create_table('action_grants',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('tenant_id', sa.Uuid(), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('principal_id', sa.Uuid(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('scope', sa.String(16), nullable=False),
        sa.Column('scope_id', sa.Uuid(), nullable=False),
        sa.Column('agent_version_id', sa.Uuid(), nullable=False),
        sa.Column('tool_name', sa.String(64), nullable=False),
        sa.Column('risk', sa.String(16), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("scope IN ('session','automation')", name='ck_action_grants_scope'))
    op.create_index('uq_action_grants_active', 'action_grants', ['scope', 'scope_id', 'agent_version_id', 'tool_name'],
                    unique=True, sqlite_where=sa.text('revoked_at IS NULL'), postgresql_where=sa.text('revoked_at IS NULL'))
    with op.batch_alter_table('action_approvals') as batch:
        batch.add_column(sa.Column('reason', sa.String(8), nullable=False, server_default='policy'))
        batch.add_column(sa.Column('risk', sa.String(16), nullable=True))


def downgrade():
    with op.batch_alter_table('action_approvals') as batch:
        batch.drop_column('risk')
        batch.drop_column('reason')
    op.drop_index('uq_action_grants_active', table_name='action_grants')
    op.drop_table('action_grants')
