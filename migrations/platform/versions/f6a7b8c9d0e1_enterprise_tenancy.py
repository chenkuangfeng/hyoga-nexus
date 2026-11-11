"""Enterprise-only tenancy, enterprise policies, built-in roles, knowledge base visibility
(openspec 2026-11-11-enterprise-saas E1, decisions 1, 3, 4, 8).

- Every tenant is an enterprise: any remaining personal space becomes a one-member enterprise in place (its
  owner keeps it, nothing is deleted) and gets an enterprise code; ``kind`` allows only ``enterprise`` and
  ``system``. The development database had no personal spaces when this was written.
- ``enterprise_policies``: one optional row per enterprise; a missing row means the defaults.
- ``tenant_roles.builtin`` plus the built-in ``security_admin`` and ``auditor`` roles for every enterprise.
- ``knowledge_bases.visibility``: existing bases stay readable by every member (``tenant``).
"""
import uuid
from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa

revision = 'f6a7b8c9d0e1'
down_revision = 'e5f6a7b8c9d0'
branch_labels = depends_on = None

BUILTIN_ROLES = {
    'security_admin': (('audit',), ('policy:manage', 'tools:manage', 'audit:read')),
    'auditor': (('audit',), ('audit:read',)),
}


def upgrade():
    bind = op.get_bind()
    # One statement per space so each gets its own code; ids are compared in the column's stored form.
    for (tenant_id,) in bind.execute(sa.text("SELECT id FROM tenants WHERE kind = 'personal'")).all():
        bind.execute(sa.text("UPDATE tenants SET kind = 'enterprise', code = COALESCE(code, :code) WHERE id = :id"),
                     {'code': f"e{uuid.uuid4().hex[:10]}", 'id': tenant_id})
    with op.batch_alter_table('tenants') as batch:
        batch.drop_constraint('ck_tenants_kind', type_='check')
        batch.create_check_constraint('ck_tenants_kind', "kind IN ('enterprise', 'system')")

    op.create_table(
        'enterprise_policies',
        sa.Column('tenant_id', sa.Uuid(), sa.ForeignKey('tenants.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('self_build_agents', sa.String(16), nullable=False, server_default='all'),
        sa.Column('self_build_org_unit_ids', sa.JSON(), nullable=False),
        sa.Column('personal_models', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('external_sharing', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('personal_wecom_channels', sa.String(16), nullable=False, server_default='review'),
        sa.Column('personal_external_channels', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('retention_days', sa.Integer()),
        sa.Column('updated_by', sa.Uuid(), sa.ForeignKey('users.id', ondelete='SET NULL')),
        sa.Column('updated_at', sa.DateTime(timezone=True)),
        sa.CheckConstraint("self_build_agents IN ('all', 'org_units', 'none')",
                           name='ck_enterprise_policies_self_build'),
        sa.CheckConstraint("personal_wecom_channels IN ('review', 'open', 'disabled')",
                           name='ck_enterprise_policies_wecom_channels'),
    )

    with op.batch_alter_table('tenant_roles') as batch:
        batch.add_column(sa.Column('builtin', sa.Boolean(), nullable=False, server_default=sa.false()))
    roles = sa.table('tenant_roles', sa.column('id', sa.Uuid()), sa.column('tenant_id', sa.Uuid()),
                     sa.column('name', sa.String()), sa.column('builtin', sa.Boolean()),
                     sa.column('created_at', sa.DateTime(timezone=True)),
                     sa.column('updated_at', sa.DateTime(timezone=True)))
    menu_grants = sa.table('tenant_role_menu_grants', sa.column('role_id', sa.Uuid()), sa.column('menu', sa.String()))
    api_grants = sa.table('tenant_role_api_grants', sa.column('role_id', sa.Uuid()),
                          sa.column('permission', sa.String()))
    tenants = sa.table('tenants', sa.column('id', sa.Uuid()), sa.column('kind', sa.String()))
    now = datetime.now(timezone.utc)
    for tenant_id in bind.execute(sa.select(tenants.c.id).where(tenants.c.kind == 'enterprise')).scalars().all():
        for name, (menus, apis) in BUILTIN_ROLES.items():
            taken = bind.execute(sa.select(roles.c.id).where(roles.c.tenant_id == tenant_id,
                                                             roles.c.name == name)).scalar()
            if taken is not None:  # an existing custom role of that name becomes the built-in role
                bind.execute(sa.update(roles).where(roles.c.id == taken).values(builtin=True))
                continue
            role_id = uuid.uuid4()
            bind.execute(sa.insert(roles).values(id=role_id, tenant_id=tenant_id, name=name, builtin=True,
                                                 created_at=now, updated_at=now))
            for menu in menus:
                bind.execute(sa.insert(menu_grants).values(role_id=role_id, menu=menu))
            for api in apis:
                bind.execute(sa.insert(api_grants).values(role_id=role_id, permission=api))

    with op.batch_alter_table('knowledge_bases') as batch:
        batch.add_column(sa.Column('visibility', sa.String(16), nullable=False, server_default='tenant'))
        batch.create_check_constraint('ck_knowledge_bases_visibility', "visibility IN ('private','tenant')")


def downgrade():
    with op.batch_alter_table('knowledge_bases') as batch:
        batch.drop_constraint('ck_knowledge_bases_visibility', type_='check')
        batch.drop_column('visibility')
    roles = sa.table('tenant_roles', sa.column('builtin', sa.Boolean()), sa.column('name', sa.String()))
    op.get_bind().execute(sa.delete(roles).where(roles.c.builtin.is_(True),
                                                 roles.c.name.in_(('security_admin', 'auditor'))))
    with op.batch_alter_table('tenant_roles') as batch:
        batch.drop_column('builtin')
    op.drop_table('enterprise_policies')
    with op.batch_alter_table('tenants') as batch:
        batch.drop_constraint('ck_tenants_kind', type_='check')
        batch.create_check_constraint('ck_tenants_kind', "kind IN ('personal', 'enterprise', 'system')")
