"""Tenant roles with menu and backend-API grants, assigned to tenant members.

Adds tenant_roles, tenant_role_menu_grants, tenant_role_api_grants and tenant_user_roles.
Existing owner/admin/member memberships keep their meaning; no rows are rewritten.
"""
from alembic import op
import sqlalchemy as sa

revision = 'a6c2d8e4f1b7'
down_revision = 'f3a7c1e2b9d4'
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        'tenant_roles',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('tenant_id', sa.Uuid(), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(64), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('tenant_id', 'name', name='uq_tenant_roles_tenant_name'),
        sa.UniqueConstraint('id', 'tenant_id', name='uq_tenant_roles_id_tenant'),
    )
    op.create_table(
        'tenant_role_menu_grants',
        sa.Column('role_id', sa.Uuid(), sa.ForeignKey('tenant_roles.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('menu', sa.String(64), primary_key=True),
    )
    op.create_table(
        'tenant_role_api_grants',
        sa.Column('role_id', sa.Uuid(), sa.ForeignKey('tenant_roles.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('permission', sa.String(64), primary_key=True),
    )
    op.create_table(
        'tenant_user_roles',
        sa.Column('tenant_id', sa.Uuid(), primary_key=True),
        sa.Column('user_id', sa.Uuid(), primary_key=True),
        sa.Column('role_id', sa.Uuid(), primary_key=True),
        sa.Column('assigned_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id', 'user_id'],
                                ['tenant_memberships.tenant_id', 'tenant_memberships.user_id'],
                                ondelete='CASCADE', name='fk_tenant_user_roles_membership'),
        sa.ForeignKeyConstraint(['role_id', 'tenant_id'], ['tenant_roles.id', 'tenant_roles.tenant_id'],
                                ondelete='CASCADE', name='fk_tenant_user_roles_role_tenant'),
    )


def downgrade():
    op.drop_table('tenant_user_roles')
    op.drop_table('tenant_role_api_grants')
    op.drop_table('tenant_role_menu_grants')
    op.drop_table('tenant_roles')
