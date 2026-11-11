"""WeCom self-built apps per enterprise and directory sync (openspec 2026-11-11-enterprise-saas E3, decision 5).

New tables ``tenant_wecom_corps``, ``tenant_wecom_apps`` and ``wecom_members``; ``org_units.external_id`` (the WeCom
department id of synced nodes); ``tenant_memberships.source`` admits ``wecom`` for accounts opened from WeCom.
"""
from alembic import op
import sqlalchemy as sa

revision = 'a7b8c9d0e1f2'
down_revision = 'f6a7b8c9d0e1'
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        'tenant_wecom_corps',
        sa.Column('tenant_id', sa.Uuid(), sa.ForeignKey('tenants.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('corp_id', sa.String(64), nullable=False, unique=True),
        sa.Column('callback_token_ciphertext', sa.Text()),
        sa.Column('encoding_aes_key_ciphertext', sa.Text()),
        sa.Column('sync_status', sa.String(16), nullable=False, server_default='never'),
        sa.Column('sync_error', sa.String(500)),
        sa.Column('synced_at', sa.DateTime(timezone=True)),
        sa.Column('updated_by', sa.Uuid(), sa.ForeignKey('users.id', ondelete='SET NULL')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        'tenant_wecom_apps',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('tenant_id', sa.Uuid(), sa.ForeignKey('tenant_wecom_corps.tenant_id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('name', sa.String(80), nullable=False),
        sa.Column('wecom_agentid', sa.String(32), nullable=False),
        sa.Column('secret_ciphertext', sa.Text(), nullable=False),
        sa.Column('purpose', sa.String(16), nullable=False),
        sa.Column('nexus_agent_id', sa.Uuid()),
        sa.Column('qr_login', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('status', sa.String(16), nullable=False, server_default='active'),
        sa.Column('created_by', sa.Uuid(), sa.ForeignKey('users.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('tenant_id', 'wecom_agentid', name='uq_wecom_apps_agentid'),
        sa.CheckConstraint("purpose IN ('workspace', 'admin', 'agent')", name='ck_wecom_apps_purpose'),
        sa.CheckConstraint("(purpose = 'agent') = (nexus_agent_id IS NOT NULL)", name='ck_wecom_apps_agent'),
        sa.CheckConstraint("status IN ('active', 'disabled')", name='ck_wecom_apps_status'),
        sa.ForeignKeyConstraint(['nexus_agent_id', 'tenant_id'], ['agents.id', 'agents.tenant_id'],
                                ondelete='CASCADE', name='fk_wecom_apps_agent_tenant'),
    )
    op.create_index('uq_wecom_apps_agent', 'tenant_wecom_apps', ['nexus_agent_id'], unique=True,
                    sqlite_where=sa.text('nexus_agent_id IS NOT NULL'),
                    postgresql_where=sa.text('nexus_agent_id IS NOT NULL'))
    op.create_index('uq_wecom_apps_qr', 'tenant_wecom_apps', ['tenant_id'], unique=True,
                    sqlite_where=sa.text('qr_login'), postgresql_where=sa.text('qr_login'))
    op.create_table(
        'wecom_members',
        sa.Column('tenant_id', sa.Uuid(), sa.ForeignKey('tenants.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('userid', sa.String(64), primary_key=True),
        sa.Column('user_id', sa.Uuid(), sa.ForeignKey('users.id', ondelete='SET NULL')),
        sa.Column('name', sa.String(160), nullable=False, server_default=''),
        sa.Column('department_ids', sa.JSON(), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('synced_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_wecom_members_user', 'wecom_members', ['tenant_id', 'user_id'])
    with op.batch_alter_table('org_units') as batch:
        batch.add_column(sa.Column('external_id', sa.String(64)))
        batch.create_unique_constraint('uq_org_units_external', ['tenant_id', 'external_id'])
    with op.batch_alter_table('tenant_memberships') as batch:
        batch.drop_constraint('ck_membership_source', type_='check')
        batch.create_check_constraint('ck_membership_source',
                                      "source IN ('manual', 'invitation', 'application', 'wecom')")


def downgrade():
    with op.batch_alter_table('tenant_memberships') as batch:
        batch.drop_constraint('ck_membership_source', type_='check')
        batch.create_check_constraint('ck_membership_source', "source IN ('manual', 'invitation', 'application')")
    with op.batch_alter_table('org_units') as batch:
        batch.drop_constraint('uq_org_units_external', type_='unique')
        batch.drop_column('external_id')
    op.drop_index('ix_wecom_members_user', table_name='wecom_members')
    op.drop_table('wecom_members')
    op.drop_index('uq_wecom_apps_qr', table_name='tenant_wecom_apps')
    op.drop_index('uq_wecom_apps_agent', table_name='tenant_wecom_apps')
    op.drop_table('tenant_wecom_apps')
    op.drop_table('tenant_wecom_corps')
