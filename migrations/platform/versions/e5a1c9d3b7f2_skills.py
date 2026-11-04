"""Skill definitions, immutable versions, version files and session index snapshots
(openspec 2026-11-04-skill-scripts, task 3.1).

Additive only: no existing table changes. Skill bindings reuse ``agent_resource_bindings``.
"""
from alembic import op
import sqlalchemy as sa

revision = 'e5a1c9d3b7f2'
down_revision = 'b8e2f1c4d7a9'
branch_labels = depends_on = None


def upgrade():
    op.create_table('skills',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('tenant_id', sa.Uuid(), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(64), nullable=False),
        sa.Column('source', sa.String(16), nullable=False, server_default='installed'),
        sa.Column('current_version_id', sa.Uuid()),
        sa.Column('created_by', sa.Uuid(), sa.ForeignKey('users.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('tenant_id', 'name', name='uq_skills_tenant_name'))
    op.create_table('skill_versions',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('skill_id', sa.Uuid(), sa.ForeignKey('skills.id', ondelete='CASCADE'), nullable=False),
        sa.Column('tenant_id', sa.Uuid(), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('skill_md', sa.Text(), nullable=False),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('tools', sa.JSON(), nullable=False),
        sa.Column('scripts', sa.JSON(), nullable=False),
        sa.Column('scan_hints', sa.JSON(), nullable=False),
        sa.Column('content_hash', sa.String(64), nullable=False),
        sa.Column('created_by', sa.Uuid(), sa.ForeignKey('users.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('skill_id', 'version', name='uq_skill_versions_number'))
    op.create_table('skill_version_files',
        sa.Column('version_id', sa.Uuid(), sa.ForeignKey('skill_versions.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('path', sa.String(200), primary_key=True),
        sa.Column('content', sa.Text(), nullable=False))
    op.create_table('session_skill_snapshots',
        sa.Column('session_id', sa.Uuid(), sa.ForeignKey('sessions.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('tenant_id', sa.Uuid(), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('agent_version_id', sa.Uuid(), sa.ForeignKey('agent_versions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('index_text', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False))


def downgrade():
    op.drop_table('session_skill_snapshots')
    op.drop_table('skill_version_files')
    op.drop_table('skill_versions')
    op.drop_table('skills')
