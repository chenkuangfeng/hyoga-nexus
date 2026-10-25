"""Scoped providers, encrypted credentials and model defaults."""
from alembic import op
import sqlalchemy as sa
revision = 'c8d240ab1701'
down_revision = 'b5a16ed22801'
branch_labels = depends_on = None


def upgrade():
    op.create_table('model_providers',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('workspace_id', sa.Uuid(), sa.ForeignKey('workspaces.id'), nullable=False),
        sa.Column('owner_user_id', sa.Uuid(), sa.ForeignKey('users.id')),
        sa.Column('name', sa.String(160), nullable=False),
        sa.Column('base_url', sa.String(512), nullable=False),
        sa.Column('credential_id', sa.Uuid(), sa.ForeignKey('credential_references.id'), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False),
        sa.Column('last_test_at', sa.DateTime(timezone=True)))
    op.create_table('provider_credentials',
        sa.Column('credential_id', sa.Uuid(), sa.ForeignKey('credential_references.id'), primary_key=True),
        sa.Column('provider_id', sa.Uuid(), sa.ForeignKey('model_providers.id'), nullable=False),
        sa.Column('base_url', sa.String(512), nullable=False),
        sa.Column('encrypted_key', sa.Text(), nullable=False))
    op.create_table('provider_models',
        sa.Column('profile_id', sa.Uuid(), sa.ForeignKey('model_profiles.id'), primary_key=True),
        sa.Column('provider_id', sa.Uuid(), sa.ForeignKey('model_providers.id'), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False))
    op.create_table('model_defaults',
        sa.Column('workspace_id', sa.Uuid(), sa.ForeignKey('workspaces.id'), primary_key=True),
        sa.Column('scope_key', sa.String(36), primary_key=True),
        sa.Column('version_id', sa.Uuid(), sa.ForeignKey('model_profile_versions.id'), nullable=False))


def downgrade():
    for name in ('model_defaults', 'provider_models', 'provider_credentials', 'model_providers'):
        op.drop_table(name)
