"""Agent-level permissions granted to tenant roles (tenant_agent_grants)."""
from alembic import op
import sqlalchemy as sa

revision = 'b7d1e5c3a9f2'
down_revision = 'a6c2d8e4f1b7'
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        'tenant_agent_grants',
        sa.Column('role_id', sa.Uuid(), primary_key=True),
        sa.Column('agent_id', sa.Uuid(), primary_key=True),
        sa.Column('tenant_id', sa.Uuid(), nullable=False),
        sa.Column('permission', sa.String(16), primary_key=True),
        sa.ForeignKeyConstraint(['agent_id', 'tenant_id'], ['agents.id', 'agents.tenant_id'],
                                ondelete='CASCADE', name='fk_tenant_agent_grants_agent_tenant'),
        sa.ForeignKeyConstraint(['role_id', 'tenant_id'], ['tenant_roles.id', 'tenant_roles.tenant_id'],
                                ondelete='CASCADE', name='fk_tenant_agent_grants_role_tenant'),
    )


def downgrade():
    op.drop_table('tenant_agent_grants')
