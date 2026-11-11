"""Token usage ledger and monthly limits (openspec 2026-11-11-enterprise-saas E6).

New tables ``usage_ledger``, ``usage_recorded_runs`` and ``usage_limits``. Past Runs are not back-filled.
"""
from alembic import op
import sqlalchemy as sa

revision = 'd0e1f2a3b4c5'
down_revision = 'c9d0e1f2a3b4'
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        'usage_ledger',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('tenant_id', sa.Uuid(), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('day', sa.Date(), nullable=False),
        sa.Column('user_id', sa.Uuid(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('agent_id', sa.Uuid()),
        sa.Column('model_version_id', sa.Uuid()),
        sa.Column('runs', sa.Integer(), nullable=False),
        sa.Column('input_tokens', sa.BigInteger(), nullable=False),
        sa.Column('output_tokens', sa.BigInteger(), nullable=False),
        sa.Column('cache_read_tokens', sa.BigInteger(), nullable=False),
        sa.Column('cache_creation_tokens', sa.BigInteger(), nullable=False),
    )
    op.create_index('ix_usage_ledger_tenant_day', 'usage_ledger', ['tenant_id', 'day'])
    op.create_index('ix_usage_ledger_user_day', 'usage_ledger', ['tenant_id', 'user_id', 'day'])
    op.create_table(
        'usage_recorded_runs',
        sa.Column('run_id', sa.Uuid(), sa.ForeignKey('runs.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('recorded_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        'usage_limits',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('tenant_id', sa.Uuid(), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('scope_kind', sa.String(16), nullable=False),
        sa.Column('scope_id', sa.Uuid(), nullable=False),
        sa.Column('monthly_tokens', sa.BigInteger(), nullable=False),
        sa.Column('updated_by', sa.Uuid(), sa.ForeignKey('users.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('tenant_id', 'scope_kind', 'scope_id', name='uq_usage_limits_scope'),
        sa.CheckConstraint("scope_kind IN ('tenant', 'org_unit', 'user')", name='ck_usage_limits_scope'),
        sa.CheckConstraint('monthly_tokens > 0', name='ck_usage_limits_positive'),
    )


def downgrade():
    op.drop_table('usage_limits')
    op.drop_table('usage_recorded_runs')
    op.drop_index('ix_usage_ledger_user_day', table_name='usage_ledger')
    op.drop_index('ix_usage_ledger_tenant_day', table_name='usage_ledger')
    op.drop_table('usage_ledger')
