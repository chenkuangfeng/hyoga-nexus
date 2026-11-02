"""Typed models: profile capability type and per-type model defaults (openspec 2026-11-02-model-management).

- `model_profiles.model_type` records the capability (chat, embedding, rerank, vision, speech).
  Existing profiles are chat models.
- `model_defaults` gains `model_type` in its primary key so each scope can keep one default per type.
  The table is rebuilt rather than altered in place because primary keys cannot be changed in place
  on SQLite and PostgreSQL alike. Existing defaults become chat defaults.

The downgrade keeps only chat defaults, because the older schema allows one default per scope.
"""
from alembic import op
import sqlalchemy as sa

revision = '0a7c3e9d1b5f'
down_revision = 'e6d1a7b3c8f2'
branch_labels = depends_on = None


def upgrade():
    op.add_column('model_profiles', sa.Column('model_type', sa.String(16), nullable=False, server_default='chat'))
    op.rename_table('model_defaults', 'model_defaults_old')
    op.create_table('model_defaults',
        sa.Column('tenant_id', sa.Uuid(), sa.ForeignKey('tenants.id'), nullable=False),
        sa.Column('scope_key', sa.String(36), nullable=False),
        sa.Column('model_type', sa.String(16), nullable=False, server_default='chat'),
        sa.Column('version_id', sa.Uuid(), sa.ForeignKey('model_profile_versions.id'), nullable=False),
        sa.PrimaryKeyConstraint('tenant_id', 'scope_key', 'model_type', name='pk_model_defaults'))
    op.execute(
        "INSERT INTO model_defaults (tenant_id, scope_key, model_type, version_id) "
        "SELECT tenant_id, scope_key, 'chat', version_id FROM model_defaults_old")
    op.drop_table('model_defaults_old')


def downgrade():
    op.rename_table('model_defaults', 'model_defaults_new')
    op.create_table('model_defaults',
        sa.Column('tenant_id', sa.Uuid(), sa.ForeignKey('tenants.id'), nullable=False),
        sa.Column('scope_key', sa.String(36), nullable=False),
        sa.Column('version_id', sa.Uuid(), sa.ForeignKey('model_profile_versions.id'), nullable=False),
        sa.PrimaryKeyConstraint('tenant_id', 'scope_key', name='pk_model_defaults_chat_only'))
    op.execute(
        "INSERT INTO model_defaults (tenant_id, scope_key, version_id) "
        "SELECT tenant_id, scope_key, version_id FROM model_defaults_new WHERE model_type = 'chat'")
    op.drop_table('model_defaults_new')
    with op.batch_alter_table('model_profiles') as batch:
        batch.drop_column('model_type')
