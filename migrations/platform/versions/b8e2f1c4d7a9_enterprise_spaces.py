"""Enterprise and personal spaces, enterprise-scoped org units, space join requests and shared spaces.

Openspec 2026-11-03-enterprise-personal-spaces, decision A (development database rebuilt):

- `tenants.kind` (`personal` | `enterprise`) and `tenants.wecom_corp_id`. Existing spaces are enterprises.
- `users.email` (unique, nullable until the email login lands) and `users.must_change_password`.
- `tenant_memberships` roles follow WeKnora: owner, admin, contributor, viewer. Existing `member` rows
  become `contributor`, the closest level. `source` is manual | invitation | application; rows with
  `organization` source are revoked, because their binding is removed.
- Organization tree rebuilt per enterprise: `org_units.tenant_id` and `source`; `user_org_units` is
  keyed by (tenant, user, unit) with composite foreign keys so only members can be placed in a node.
  `tenant_org_bindings` is removed. Existing tree data is discarded by decision A.
- `sessions.org_unit_id` snapshot is removed: organization nodes no longer affect access.
- New tables: `space_join_requests` (user to enterprise application or invitation) and the shared-space
  tables `shared_spaces`, `shared_space_tenant_members`, `shared_space_join_requests` (WeKnora's
  organization model, named shared_space in Nexus).
"""
from alembic import op
import sqlalchemy as sa

revision = 'b8e2f1c4d7a9'
down_revision = '0a7c3e9d1b5f'
branch_labels = depends_on = None

MEMBERSHIP_ROLES = "role IN ('owner', 'admin', 'contributor', 'viewer')"
MEMBERSHIP_SOURCES = "source IN ('manual', 'invitation', 'application')"


def upgrade():
    # Spaces: kind and WeCom corp binding record.
    with op.batch_alter_table('tenants') as batch:
        batch.add_column(sa.Column('kind', sa.String(16), nullable=False, server_default='enterprise'))
        batch.add_column(sa.Column('wecom_corp_id', sa.String(64), nullable=True))
        # Enterprise code used at registration to join or create an enterprise; unique among spaces that have one.
        batch.add_column(sa.Column('code', sa.String(32), nullable=True))
        batch.create_unique_constraint('uq_tenants_code', ['code'])
        batch.create_check_constraint('ck_tenants_kind', "kind IN ('personal', 'enterprise')")

    # Users: email login identifier and forced password change.
    with op.batch_alter_table('users') as batch:
        batch.add_column(sa.Column('email', sa.String(255), nullable=True))
        batch.add_column(sa.Column('must_change_password', sa.Boolean(), nullable=False,
                                   server_default=sa.false()))
        # Per-user preferences, e.g. the last space the user worked in (`last_active_tenant_id`).
        batch.add_column(sa.Column('preferences', sa.JSON(), nullable=False, server_default='{}'))
    op.create_index('uq_users_email', 'users', ['email'], unique=True)

    # Memberships: map old roles and sources, then replace the checks.
    op.execute("UPDATE tenant_memberships SET role = 'contributor' WHERE role = 'member'")
    op.execute(
        "UPDATE tenant_memberships SET source = 'manual', status = 'revoked', "
        "revoked_at = CURRENT_TIMESTAMP WHERE source = 'organization'"
    )
    with op.batch_alter_table('tenant_memberships') as batch:
        batch.drop_constraint('ck_membership_role', type_='check')
        batch.drop_constraint('ck_membership_source', type_='check')
        batch.create_check_constraint('ck_membership_role', MEMBERSHIP_ROLES)
        batch.create_check_constraint('ck_membership_source', MEMBERSHIP_SOURCES)

    # Sessions: the organization snapshot no longer affects access.
    with op.batch_alter_table('sessions') as batch:
        batch.drop_constraint('fk_sessions_org_unit_id', type_='foreignkey')
        batch.drop_column('org_unit_id')

    # Organization tree: drop the global tree and its bindings (decision A), then recreate per enterprise.
    op.drop_table('user_org_units')
    op.drop_table('tenant_org_bindings')
    op.drop_table('org_units')
    op.create_table(
        'org_units',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('tenant_id', sa.Uuid(), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('root_id', sa.Uuid(), sa.ForeignKey('org_units.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('parent_id', sa.Uuid(), sa.ForeignKey('org_units.id', ondelete='RESTRICT'), nullable=True),
        sa.Column('name', sa.String(160), nullable=False),
        sa.Column('status', sa.String(16), nullable=False, server_default='active'),
        sa.Column('source', sa.String(16), nullable=False, server_default='manual'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('parent_id', 'name', name='uq_org_units_parent_name'),
        sa.UniqueConstraint('tenant_id', 'id', name='uq_org_units_tenant_id'),
        sa.CheckConstraint("status IN ('active', 'disabled')", name='ck_org_units_status'),
        sa.CheckConstraint("source IN ('manual', 'wecom')", name='ck_org_units_source'),
    )
    op.create_index('ix_org_units_root', 'org_units', ['root_id'])
    op.create_index('ix_org_units_tenant', 'org_units', ['tenant_id'])
    op.create_table(
        'user_org_units',
        sa.Column('tenant_id', sa.Uuid(), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('unit_id', sa.Uuid(), nullable=False),
        sa.Column('is_primary', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('tenant_id', 'user_id', 'unit_id'),
        sa.ForeignKeyConstraint(['tenant_id', 'user_id'], ['tenant_memberships.tenant_id', 'tenant_memberships.user_id'],
                                name='fk_user_org_units_membership', ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['tenant_id', 'unit_id'], ['org_units.tenant_id', 'org_units.id'],
                                name='fk_user_org_units_unit', ondelete='RESTRICT'),
    )
    # At most one primary node per member per enterprise.
    op.create_index('uq_user_org_units_primary', 'user_org_units', ['tenant_id', 'user_id'], unique=True,
                    sqlite_where=sa.text('is_primary = 1'), postgresql_where=sa.text('is_primary'))

    # Enterprise applications and invitations.
    op.create_table(
        'space_join_requests',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('tenant_id', sa.Uuid(), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_id', sa.Uuid(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('direction', sa.String(16), nullable=False),
        sa.Column('status', sa.String(16), nullable=False, server_default='pending'),
        sa.Column('role', sa.String(16), nullable=False, server_default='contributor'),
        sa.Column('unit_id', sa.Uuid(), nullable=True),
        sa.Column('message', sa.Text(), nullable=True),
        sa.Column('reject_reason', sa.Text(), nullable=True),
        sa.Column('cooldown_until', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_by', sa.Uuid(), sa.ForeignKey('users.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('reviewed_by', sa.Uuid(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id', 'unit_id'], ['org_units.tenant_id', 'org_units.id'],
                                name='fk_space_join_requests_unit', ondelete='RESTRICT'),
        sa.CheckConstraint("direction IN ('application', 'invitation')", name='ck_space_join_requests_direction'),
        sa.CheckConstraint("status IN ('pending', 'approved', 'rejected', 'withdrawn')",
                           name='ck_space_join_requests_status'),
        sa.CheckConstraint("role IN ('admin', 'contributor', 'viewer')", name='ck_space_join_requests_role'),
    )
    # One pending request (application or invitation) per person per enterprise.
    op.create_index('uq_space_join_requests_pending', 'space_join_requests', ['tenant_id', 'user_id'], unique=True,
                    sqlite_where=sa.text("status = 'pending'"), postgresql_where=sa.text("status = 'pending'"))

    # Shared spaces (WeKnora organizations).
    op.create_table(
        'shared_spaces',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('name', sa.String(160), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('owner_user_id', sa.Uuid(), sa.ForeignKey('users.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('owner_tenant_id', sa.Uuid(), sa.ForeignKey('tenants.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('invite_code', sa.String(32), nullable=True),
        sa.Column('invite_code_expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('invite_code_validity_days', sa.Integer(), nullable=False, server_default='7'),
        sa.Column('require_approval', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('searchable', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('member_limit', sa.Integer(), nullable=False, server_default='50'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint('invite_code', name='uq_shared_spaces_invite_code'),
    )
    op.create_index('ix_shared_spaces_owner_tenant', 'shared_spaces', ['owner_tenant_id'])
    op.create_table(
        'shared_space_tenant_members',
        sa.Column('shared_space_id', sa.Uuid(), sa.ForeignKey('shared_spaces.id', ondelete='CASCADE'),
                  primary_key=True),
        sa.Column('tenant_id', sa.Uuid(), sa.ForeignKey('tenants.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('role', sa.String(16), nullable=False, server_default='viewer'),
        sa.Column('representative_user_id', sa.Uuid(), sa.ForeignKey('users.id', ondelete='SET NULL'),
                  nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("role IN ('admin', 'editor', 'viewer')", name='ck_shared_space_members_role'),
    )
    op.create_index('ix_shared_space_members_tenant', 'shared_space_tenant_members', ['tenant_id'])
    op.create_table(
        'shared_space_join_requests',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('shared_space_id', sa.Uuid(), sa.ForeignKey('shared_spaces.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('tenant_id', sa.Uuid(), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_id', sa.Uuid(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('request_type', sa.String(16), nullable=False, server_default='join'),
        sa.Column('prev_role', sa.String(16), nullable=True),
        sa.Column('requested_role', sa.String(16), nullable=False, server_default='viewer'),
        sa.Column('status', sa.String(16), nullable=False, server_default='pending'),
        sa.Column('message', sa.Text(), nullable=True),
        sa.Column('reviewed_by', sa.Uuid(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('review_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("request_type IN ('join', 'upgrade')", name='ck_shared_space_join_type'),
        sa.CheckConstraint("requested_role IN ('admin', 'editor', 'viewer')", name='ck_shared_space_join_role'),
        sa.CheckConstraint("status IN ('pending', 'approved', 'rejected')", name='ck_shared_space_join_status'),
    )
    op.create_index('uq_shared_space_join_pending', 'shared_space_join_requests',
                    ['shared_space_id', 'tenant_id', 'request_type'], unique=True,
                    sqlite_where=sa.text("status = 'pending'"), postgresql_where=sa.text("status = 'pending'"))


def downgrade():
    op.drop_index('uq_shared_space_join_pending', table_name='shared_space_join_requests')
    op.drop_table('shared_space_join_requests')
    op.drop_index('ix_shared_space_members_tenant', table_name='shared_space_tenant_members')
    op.drop_table('shared_space_tenant_members')
    op.drop_index('ix_shared_spaces_owner_tenant', table_name='shared_spaces')
    op.drop_table('shared_spaces')
    op.drop_index('uq_space_join_requests_pending', table_name='space_join_requests')
    op.drop_table('space_join_requests')
    op.drop_index('uq_user_org_units_primary', table_name='user_org_units')
    op.drop_table('user_org_units')
    op.drop_index('ix_org_units_tenant', table_name='org_units')
    op.drop_index('ix_org_units_root', table_name='org_units')
    op.drop_table('org_units')

    # Recreate the global tree shape from d1f5b8c2a9e4 and the binding table; data is not restored.
    op.create_table(
        'org_units',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('root_id', sa.Uuid(), sa.ForeignKey('org_units.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('parent_id', sa.Uuid(), sa.ForeignKey('org_units.id', ondelete='RESTRICT'), nullable=True),
        sa.Column('name', sa.String(160), nullable=False),
        sa.Column('status', sa.String(16), nullable=False, server_default='active'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('parent_id', 'name', name='uq_org_units_parent_name'),
        sa.CheckConstraint("status IN ('active', 'disabled')", name='ck_org_units_status'),
    )
    op.create_index('ix_org_units_root', 'org_units', ['root_id'])
    op.create_table(
        'tenant_org_bindings',
        sa.Column('tenant_id', sa.Uuid(), sa.ForeignKey('tenants.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('unit_id', sa.Uuid(), sa.ForeignKey('org_units.id', ondelete='RESTRICT'), primary_key=True),
        sa.Column('created_by', sa.Uuid(), sa.ForeignKey('users.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_tenant_org_bindings_unit', 'tenant_org_bindings', ['unit_id'])
    op.create_table(
        'user_org_units',
        sa.Column('user_id', sa.Uuid(), sa.ForeignKey('users.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('unit_id', sa.Uuid(), sa.ForeignKey('org_units.id', ondelete='RESTRICT'), primary_key=True),
        sa.Column('is_primary', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('uq_user_org_units_primary', 'user_org_units', ['user_id'], unique=True,
                    sqlite_where=sa.text('is_primary = 1'), postgresql_where=sa.text('is_primary'))

    with op.batch_alter_table('sessions') as batch:
        batch.add_column(sa.Column('org_unit_id', sa.Uuid(), nullable=True))
        batch.create_foreign_key('fk_sessions_org_unit_id', 'org_units', ['org_unit_id'], ['id'], ondelete='SET NULL')

    op.execute("UPDATE tenant_memberships SET role = 'member' WHERE role = 'contributor' OR role = 'viewer'")
    with op.batch_alter_table('tenant_memberships') as batch:
        batch.drop_constraint('ck_membership_role', type_='check')
        batch.drop_constraint('ck_membership_source', type_='check')
        batch.create_check_constraint('ck_membership_role', "role IN ('owner', 'admin', 'member')")
        batch.create_check_constraint('ck_membership_source', "source IN ('manual', 'organization')")

    op.drop_index('uq_users_email', table_name='users')
    with op.batch_alter_table('users') as batch:
        batch.drop_column('preferences')
        batch.drop_column('must_change_password')
        batch.drop_column('email')
    with op.batch_alter_table('tenants') as batch:
        batch.drop_constraint('ck_tenants_kind', type_='check')
        batch.drop_constraint('uq_tenants_code', type_='unique')
        batch.drop_column('code')
        batch.drop_column('wecom_corp_id')
        batch.drop_column('kind')
