"""Track independent manual and WeCom contributions to organization links."""
from alembic import op
import sqlalchemy as sa

revision = 'a03b51d982ef'
down_revision = 'f0e1d2c3b4a5'
branch_labels = depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('user_org_units') as batch:
        batch.add_column(sa.Column('source', sa.String(16), nullable=False, server_default='manual'))
        batch.create_check_constraint('ck_user_org_units_source', "source IN ('manual', 'wecom', 'mixed')")
    bind = op.get_bind()
    links = sa.table('user_org_units', sa.column('tenant_id', sa.Uuid()), sa.column('user_id', sa.Uuid()),
                     sa.column('unit_id', sa.Uuid()), sa.column('source', sa.String()))
    nodes = sa.table('org_units', sa.column('id', sa.Uuid()), sa.column('external_id', sa.String()))
    members = sa.table('wecom_members', sa.column('tenant_id', sa.Uuid()), sa.column('user_id', sa.Uuid()),
                       sa.column('department_ids', sa.JSON()))
    # Only directory-confirmed associations can be inferred; preserve all other existing links as manual.
    rows = bind.execute(sa.select(links.c.tenant_id, links.c.user_id, links.c.unit_id,
                                  nodes.c.external_id, members.c.department_ids)
        .select_from(links.join(nodes, nodes.c.id == links.c.unit_id).join(members,
            (members.c.tenant_id == links.c.tenant_id) & (members.c.user_id == links.c.user_id)))
        .where(nodes.c.external_id.is_not(None))).all()
    for tenant_id, user_id, unit_id, external_id, department_ids in rows:
        if external_id in {str(value) for value in (department_ids or [])}:
            bind.execute(links.update().where(links.c.tenant_id == tenant_id, links.c.user_id == user_id,
                                              links.c.unit_id == unit_id).values(source='wecom'))


def downgrade() -> None:
    with op.batch_alter_table('user_org_units') as batch:
        batch.drop_constraint('ck_user_org_units_source', type_='check')
        batch.drop_column('source')
