"""Organization tree, person-to-node membership, space bindings and platform admin flag.

Openspec 2026-11-01-user-org-management. Existing rows are unaffected: no space is bound yet and
no user is a platform admin until an operator sets the flag.
"""
from alembic import op
import sqlalchemy as sa

revision = 'd1f5b8c2a9e4'
down_revision = 'c4e8a2d6f1b9'
branch_labels = depends_on = None


def upgrade():
    op.add_column('users', sa.Column('is_platform_admin', sa.Boolean(), nullable=False,
                                     server_default=sa.false()))
    op.create_table('org_units',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('root_id', sa.Uuid(), sa.ForeignKey('org_units.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('parent_id', sa.Uuid(), sa.ForeignKey('org_units.id', ondelete='RESTRICT')),
        sa.Column('name', sa.String(160), nullable=False),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('parent_id', 'name', name='uq_org_units_parent_name'),
        sa.CheckConstraint("status IN ('active', 'disabled')", name='ck_org_units_status'))
    op.create_index('ix_org_units_root', 'org_units', ['root_id'])
    op.create_table('user_org_units',
        sa.Column('user_id', sa.Uuid(), sa.ForeignKey('users.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('unit_id', sa.Uuid(), sa.ForeignKey('org_units.id', ondelete='RESTRICT'), primary_key=True),
        sa.Column('is_primary', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False))
    op.create_index('uq_user_org_units_primary', 'user_org_units', ['user_id'], unique=True,
                    sqlite_where=sa.text('is_primary = 1'), postgresql_where=sa.text('is_primary'))
    op.create_table('tenant_org_bindings',
        sa.Column('tenant_id', sa.Uuid(), sa.ForeignKey('tenants.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('unit_id', sa.Uuid(), sa.ForeignKey('org_units.id', ondelete='RESTRICT'), primary_key=True),
        sa.Column('created_by', sa.Uuid(), sa.ForeignKey('users.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False))
    op.create_index('ix_tenant_org_bindings_unit', 'tenant_org_bindings', ['unit_id'])
    op.create_table('org_audit_records',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('root_id', sa.Uuid(), nullable=False),
        sa.Column('actor_user_id', sa.Uuid(), sa.ForeignKey('users.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('action', sa.String(100), nullable=False),
        sa.Column('target_type', sa.String(80), nullable=False),
        sa.Column('target_id', sa.String(255), nullable=False),
        sa.Column('metadata_json', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False))
    op.create_index('ix_org_audit_root_time', 'org_audit_records', ['root_id', 'created_at'])


def downgrade():
    op.drop_index('ix_org_audit_root_time', table_name='org_audit_records')
    op.drop_table('org_audit_records')
    op.drop_index('ix_tenant_org_bindings_unit', table_name='tenant_org_bindings')
    op.drop_table('tenant_org_bindings')
    op.drop_index('uq_user_org_units_primary', table_name='user_org_units')
    op.drop_table('user_org_units')
    op.drop_index('ix_org_units_root', table_name='org_units')
    op.drop_table('org_units')
    with op.batch_alter_table('users') as batch:
        batch.drop_column('is_platform_admin')
