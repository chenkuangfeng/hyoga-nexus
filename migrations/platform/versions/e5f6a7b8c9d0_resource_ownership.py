"""Resource ownership and knowledge base maintainers (openspec 2026-11-11-enterprise-saas E0, decision 2).

- ``agents.ownership`` and ``knowledge_bases.ownership``: ``personal`` (maintained by the creator) or ``enterprise``
  (maintained by holders of ``enterprise_agents:manage`` / ``enterprise_kbs:manage``). Existing rows become
  ``enterprise``, which keeps today's behaviour: owners and admins hold both permissions by default.
- ``knowledge_base_maintainers``: members who may maintain the content of an enterprise knowledge base.
- ``tenant_agent_grants``: assignment now grants use only. ``manage`` becomes ``view`` + ``run``; ``edit`` and
  ``publish`` become ``view``. The rows are rewritten, not dropped, so assigned members keep what they could use.
"""
from alembic import op
import sqlalchemy as sa

revision = 'e5f6a7b8c9d0'
down_revision = 'd3e4f5a6b7c8'
branch_labels = depends_on = None


def upgrade():
    with op.batch_alter_table('agents') as batch:
        batch.add_column(sa.Column('ownership', sa.String(16), nullable=False, server_default='enterprise'))
        batch.create_check_constraint('ck_agents_ownership', "ownership IN ('personal', 'enterprise')")
    with op.batch_alter_table('knowledge_bases') as batch:
        batch.add_column(sa.Column('ownership', sa.String(16), nullable=False, server_default='enterprise'))
        batch.create_check_constraint('ck_knowledge_bases_ownership', "ownership IN ('personal','enterprise')")
        batch.create_unique_constraint('uq_knowledge_bases_id_tenant', ['id', 'tenant_id'])
    op.create_table(
        'knowledge_base_maintainers',
        sa.Column('kb_id', sa.Uuid(), primary_key=True),
        sa.Column('user_id', sa.Uuid(), primary_key=True),
        sa.Column('tenant_id', sa.Uuid(), nullable=False),
        sa.Column('granted_by', sa.Uuid(), sa.ForeignKey('users.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('granted_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['kb_id', 'tenant_id'], ['knowledge_bases.id', 'knowledge_bases.tenant_id'],
                                ondelete='CASCADE', name='fk_kb_maintainers_kb_tenant'),
        sa.ForeignKeyConstraint(['tenant_id', 'user_id'],
                                ['tenant_memberships.tenant_id', 'tenant_memberships.user_id'],
                                ondelete='CASCADE', name='fk_kb_maintainers_membership'),
    )
    op.create_index('ix_kb_maintainers_user', 'knowledge_base_maintainers', ['tenant_id', 'user_id'])
    # Narrow agent assignment to use: add the implied view/run rows first, then drop the maintenance rows.
    op.execute(
        "INSERT INTO tenant_agent_grants (role_id, agent_id, tenant_id, permission) "
        "SELECT DISTINCT g.role_id, g.agent_id, g.tenant_id, 'view' FROM tenant_agent_grants g "
        "WHERE g.permission IN ('edit', 'publish', 'manage') AND NOT EXISTS ("
        "SELECT 1 FROM tenant_agent_grants v WHERE v.role_id = g.role_id AND v.agent_id = g.agent_id "
        "AND v.permission = 'view')"
    )
    op.execute(
        "INSERT INTO tenant_agent_grants (role_id, agent_id, tenant_id, permission) "
        "SELECT DISTINCT g.role_id, g.agent_id, g.tenant_id, 'run' FROM tenant_agent_grants g "
        "WHERE g.permission = 'manage' AND NOT EXISTS ("
        "SELECT 1 FROM tenant_agent_grants r WHERE r.role_id = g.role_id AND r.agent_id = g.agent_id "
        "AND r.permission = 'run')"
    )
    op.execute("DELETE FROM tenant_agent_grants WHERE permission IN ('edit', 'publish', 'manage')")


def downgrade():
    # The narrowed grants are not widened again: maintenance rights cannot be inferred from use rights.
    op.drop_index('ix_kb_maintainers_user', table_name='knowledge_base_maintainers')
    op.drop_table('knowledge_base_maintainers')
    with op.batch_alter_table('knowledge_bases') as batch:
        batch.drop_constraint('uq_knowledge_bases_id_tenant', type_='unique')
        batch.drop_constraint('ck_knowledge_bases_ownership', type_='check')
        batch.drop_column('ownership')
    with op.batch_alter_table('agents') as batch:
        batch.drop_constraint('ck_agents_ownership', type_='check')
        batch.drop_column('ownership')
