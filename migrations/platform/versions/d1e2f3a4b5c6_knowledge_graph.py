"""Knowledge graph tables (openspec 2026-11-06-knowledge-base K2).

Graph stores registry, resumable graph builds (the build row is also the job), entities, relations,
communities with reports, and the per-chunk extraction cache that lets a rebuild call the model only for
new text.

Revision ID: d1e2f3a4b5c6
Revises: c8d9e0f1a2b3
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd1e2f3a4b5c6'
down_revision: Union[str, None] = 'c8d9e0f1a2b3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('knowledge_graph_extractions',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('kb_id', sa.Uuid(), nullable=False),
    sa.Column('cache_key', sa.String(length=64), nullable=False),
    sa.Column('result', sa.JSON(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('kb_id', 'cache_key', name='uq_graph_extraction_key')
    )
    op.create_table('graph_stores',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.String(length=160), nullable=False),
    sa.Column('engine', sa.String(length=32), nullable=False),
    sa.Column('connection_config', sa.JSON(), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tenant_id', 'name', name='uq_graph_stores_name')
    )
    op.create_table('knowledge_graph_builds',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('kb_id', sa.Uuid(), nullable=False),
    sa.Column('mode', sa.String(length=24), nullable=False),
    sa.Column('store', sa.String(length=36), nullable=False),
    sa.Column('state', sa.String(length=16), nullable=False),
    sa.Column('stage', sa.String(length=16), nullable=False),
    sa.Column('progress', sa.JSON(), nullable=False),
    sa.Column('version_ids', sa.JSON(), nullable=False),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('available_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('entity_count', sa.Integer(), nullable=False),
    sa.Column('relation_count', sa.Integer(), nullable=False),
    sa.Column('community_count', sa.Integer(), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("state IN ('pending','running','ready','failed','superseded','cancelled')", name='ck_graph_builds_state'),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_graph_builds_due', 'knowledge_graph_builds', ['state', 'available_at'], unique=False)
    op.create_index('ix_graph_builds_kb', 'knowledge_graph_builds', ['kb_id', 'state'], unique=False)
    op.create_table('knowledge_graph_communities',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('build_id', sa.Uuid(), nullable=False),
    sa.Column('kb_id', sa.Uuid(), nullable=False),
    sa.Column('level', sa.Integer(), nullable=False),
    sa.Column('entity_ids', sa.JSON(), nullable=False),
    sa.Column('title', sa.String(length=255), nullable=False),
    sa.Column('summary', sa.Text(), nullable=False),
    sa.Column('sources', sa.JSON(), nullable=False),
    sa.ForeignKeyConstraint(['build_id'], ['knowledge_graph_builds.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_graph_communities_build', 'knowledge_graph_communities', ['build_id'], unique=False)
    op.create_table('knowledge_graph_entities',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('build_id', sa.Uuid(), nullable=False),
    sa.Column('kb_id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('norm', sa.String(length=255), nullable=False),
    sa.Column('entity_type', sa.String(length=64), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('sources', sa.JSON(), nullable=False),
    sa.Column('degree', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['build_id'], ['knowledge_graph_builds.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_graph_entities_build', 'knowledge_graph_entities', ['build_id'], unique=False)
    op.create_table('knowledge_graph_relations',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('build_id', sa.Uuid(), nullable=False),
    sa.Column('kb_id', sa.Uuid(), nullable=False),
    sa.Column('source_id', sa.Uuid(), nullable=False),
    sa.Column('target_id', sa.Uuid(), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('keywords', sa.JSON(), nullable=False),
    sa.Column('weight', sa.Float(), nullable=False),
    sa.Column('sources', sa.JSON(), nullable=False),
    sa.ForeignKeyConstraint(['build_id'], ['knowledge_graph_builds.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_graph_relations_build', 'knowledge_graph_relations', ['build_id'], unique=False)


def downgrade() -> None:
    op.drop_table('knowledge_graph_relations')
    op.drop_index('ix_graph_entities_build', table_name='knowledge_graph_entities')
    op.drop_table('knowledge_graph_entities')
    op.drop_index('ix_graph_communities_build', table_name='knowledge_graph_communities')
    op.drop_table('knowledge_graph_communities')
    op.drop_index('ix_graph_builds_kb', table_name='knowledge_graph_builds')
    op.drop_index('ix_graph_builds_due', table_name='knowledge_graph_builds')
    op.drop_table('knowledge_graph_builds')
    op.drop_table('graph_stores')
    op.drop_table('knowledge_graph_extractions')
