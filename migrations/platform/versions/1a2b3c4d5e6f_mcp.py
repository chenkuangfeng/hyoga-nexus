"""MCP services, tool cache/whitelist, risk policy, OAuth and stateless endpoints (openspec 2026-11-08-mcp, task 1.1 + 2.2).

Additive only: no existing table changes. Column defaults live on the ORM mappings (Python side), so
no server defaults are emitted here; the migration must compare clean against the metadata.
"""
from alembic import op
import sqlalchemy as sa

revision = '1a2b3c4d5e6f'
down_revision = 'b6c7d8e9f0a1'
branch_labels = depends_on = None


def upgrade():
    op.create_table('mcp_services',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('tenant_id', sa.Uuid(), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(64), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('transport', sa.String(24), nullable=False),
        sa.Column('config', sa.JSON(), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False),
        sa.Column('config_epoch', sa.String(64), nullable=False),
        sa.Column('created_by', sa.Uuid(), sa.ForeignKey('users.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('tenant_id', 'name', name='uq_mcp_services_tenant_name'))
    op.create_index('ix_mcp_services_tenant', 'mcp_services', ['tenant_id', 'enabled'])
    op.create_table('mcp_service_tools',
        sa.Column('service_id', sa.Uuid(), sa.ForeignKey('mcp_services.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('tool_name', sa.String(255), primary_key=True),
        sa.Column('enabled', sa.Boolean(), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('input_schema', sa.JSON(), nullable=False),
        sa.Column('output_schema', sa.JSON(), nullable=True),
        sa.Column('read_only_hint', sa.Boolean(), nullable=False),
        sa.Column('catalog_status', sa.String(16), nullable=False),
        sa.Column('catalog_error', sa.Text(), nullable=True),
        sa.Column('fingerprint', sa.String(64), nullable=False),
        sa.Column('config_epoch', sa.String(64), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False))
    op.create_index('ix_mcp_service_tools_service', 'mcp_service_tools', ['service_id', 'catalog_status'])
    op.create_table('mcp_tool_approvals',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('tenant_id', sa.Uuid(), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('service_id', sa.Uuid(), sa.ForeignKey('mcp_services.id', ondelete='CASCADE'), nullable=False),
        sa.Column('tool_name', sa.String(255), nullable=False),
        sa.Column('explicit_risk', sa.String(16), nullable=True),
        sa.Column('observed_risk', sa.String(16), nullable=True),
        sa.Column('require_approval', sa.Boolean(), nullable=False),
        sa.Column('pending_downgrade', sa.Boolean(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('tenant_id', 'service_id', 'tool_name', name='uq_mcp_tool_approvals'))
    op.create_table('mcp_oauth_clients',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('tenant_id', sa.Uuid(), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('service_id', sa.Uuid(), sa.ForeignKey('mcp_services.id', ondelete='CASCADE'), nullable=False),
        sa.Column('client_id', sa.String(512), nullable=False),
        sa.Column('client_secret', sa.Text(), nullable=True),
        sa.Column('redirect_uri', sa.String(1024), nullable=False),
        sa.Column('auth_server_metadata_url', sa.String(1024), nullable=False),
        sa.Column('registration_access_token', sa.Text(), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('tenant_id', 'service_id', name='uq_mcp_oauth_clients'))
    op.create_table('mcp_oauth_tokens',
        sa.Column('tenant_id', sa.Uuid(), sa.ForeignKey('tenants.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('principal_id', sa.Uuid(), sa.ForeignKey('users.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('service_id', sa.Uuid(), sa.ForeignKey('mcp_services.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('access_token', sa.Text(), nullable=False),
        sa.Column('refresh_token', sa.Text(), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('scope', sa.Text(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False))
    op.create_table('mcp_endpoints',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('tenant_id', sa.Uuid(), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(64), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False),
        sa.Column('tool_allowlist', sa.JSON(), nullable=False),
        sa.Column('kb_ids', sa.JSON(), nullable=False),
        sa.Column('token_hash', sa.String(64), nullable=False),
        sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_by', sa.Uuid(), sa.ForeignKey('users.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('tenant_id', 'name', name='uq_mcp_endpoints_tenant_name'))
    op.create_index('ix_mcp_endpoints_tenant', 'mcp_endpoints', ['tenant_id', 'enabled'])


def downgrade():
    op.drop_index('ix_mcp_endpoints_tenant', table_name='mcp_endpoints')
    op.drop_table('mcp_endpoints')
    op.drop_table('mcp_oauth_tokens')
    op.drop_table('mcp_oauth_clients')
    op.drop_table('mcp_tool_approvals')
    op.drop_index('ix_mcp_service_tools_service', table_name='mcp_service_tools')
    op.drop_table('mcp_service_tools')
    op.drop_index('ix_mcp_services_tenant', table_name='mcp_services')
    op.drop_table('mcp_services')
