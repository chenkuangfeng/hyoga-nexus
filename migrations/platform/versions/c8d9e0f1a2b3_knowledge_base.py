"""Knowledge base tables (openspec 2026-11-06-knowledge-base K1.3).

Knowledge bases, documents, immutable document versions, chunk text with positions, resumable jobs, and the
space-level registries of vector stores and storage backends. Vectors and keyword postings live in the
selected vector store (derived data). Active names are unique through partial indexes, so a deleted base or
document can be re-created under the same name while its cleanup job is still running.

Revision ID: c8d9e0f1a2b3
Revises: b7c6d5e4f3a2
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c8d9e0f1a2b3'
down_revision: Union[str, None] = 'b7c6d5e4f3a2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('knowledge_jobs',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('kb_id', sa.Uuid(), nullable=False),
    sa.Column('document_id', sa.Uuid(), nullable=True),
    sa.Column('version_id', sa.Uuid(), nullable=True),
    sa.Column('kind', sa.String(length=16), nullable=False),
    sa.Column('state', sa.String(length=16), nullable=False),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('available_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("kind IN ('index','cleanup')", name='ck_knowledge_jobs_kind'),
    sa.CheckConstraint("state IN ('pending','done','failed','cancelled')", name='ck_knowledge_jobs_state'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_knowledge_jobs_due', 'knowledge_jobs', ['state', 'available_at'], unique=False)
    op.create_table('storage_backends',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.String(length=160), nullable=False),
    sa.Column('provider', sa.String(length=32), nullable=False),
    sa.Column('config', sa.JSON(), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tenant_id', 'name', name='uq_storage_backends_name')
    )
    op.create_table('vector_stores',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.String(length=160), nullable=False),
    sa.Column('engine', sa.String(length=32), nullable=False),
    sa.Column('connection_config', sa.JSON(), nullable=False),
    sa.Column('index_config', sa.JSON(), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tenant_id', 'name', name='uq_vector_stores_name')
    )
    op.create_table('knowledge_bases',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.String(length=160), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('kb_type', sa.String(length=16), nullable=False),
    sa.Column('indexing', sa.JSON(), nullable=False),
    sa.Column('vector_store_id', sa.Uuid(), nullable=True),
    sa.Column('storage_backend_id', sa.Uuid(), nullable=True),
    sa.Column('embedding_model_version_id', sa.Uuid(), nullable=True),
    sa.Column('embedding_dimension', sa.Integer(), nullable=True),
    sa.Column('chunk_size', sa.Integer(), nullable=False),
    sa.Column('chunk_overlap', sa.Integer(), nullable=False),
    sa.Column('settings', sa.JSON(), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("status IN ('active','deleting')", name='ck_knowledge_bases_status'),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['storage_backend_id'], ['storage_backends.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['vector_store_id'], ['vector_stores.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_knowledge_bases_tenant', 'knowledge_bases', ['tenant_id', 'status'], unique=False)
    op.create_index('uq_knowledge_bases_name', 'knowledge_bases', ['tenant_id', 'name'], unique=True, sqlite_where=sa.text("status = 'active'"), postgresql_where=sa.text("status = 'active'"))
    op.create_table('knowledge_documents',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('kb_id', sa.Uuid(), nullable=False),
    sa.Column('filename', sa.String(length=255), nullable=False),
    sa.Column('current_version_id', sa.Uuid(), nullable=True),
    sa.Column('latest_version_id', sa.Uuid(), nullable=True),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("status IN ('active','deleting')", name='ck_knowledge_documents_status'),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['kb_id'], ['knowledge_bases.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_knowledge_documents_kb', 'knowledge_documents', ['kb_id', 'status'], unique=False)
    op.create_index('uq_knowledge_documents_name', 'knowledge_documents', ['kb_id', 'filename'], unique=True, sqlite_where=sa.text("status = 'active'"), postgresql_where=sa.text("status = 'active'"))
    op.create_table('knowledge_document_versions',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('kb_id', sa.Uuid(), nullable=False),
    sa.Column('document_id', sa.Uuid(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('content_hash', sa.String(length=64), nullable=False),
    sa.Column('blob_key', sa.String(length=512), nullable=False),
    sa.Column('size', sa.BigInteger(), nullable=False),
    sa.Column('mime', sa.String(length=128), nullable=False),
    sa.Column('state', sa.String(length=16), nullable=False),
    sa.Column('chunk_count', sa.Integer(), nullable=False),
    sa.Column('indexed_count', sa.Integer(), nullable=False),
    sa.Column('error_code', sa.String(length=64), nullable=True),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.Column('created_by', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("state IN ('pending','parsed','embedded','ready','failed','superseded')", name='ck_knowledge_versions_state'),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['document_id'], ['knowledge_documents.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['kb_id'], ['knowledge_bases.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('document_id', 'version', name='uq_knowledge_versions_number')
    )
    op.create_index('ix_knowledge_versions_hash', 'knowledge_document_versions', ['kb_id', 'content_hash'], unique=False)
    op.create_table('knowledge_chunks',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('kb_id', sa.Uuid(), nullable=False),
    sa.Column('version_id', sa.Uuid(), nullable=False),
    sa.Column('ordinal', sa.Integer(), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('page', sa.Integer(), nullable=True),
    sa.Column('section', sa.JSON(), nullable=False),
    sa.Column('char_start', sa.Integer(), nullable=False),
    sa.Column('char_end', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['kb_id'], ['knowledge_bases.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['version_id'], ['knowledge_document_versions.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('version_id', 'ordinal', name='uq_knowledge_chunks_ordinal')
    )


def downgrade() -> None:
    op.drop_table('knowledge_chunks')
    op.drop_index('ix_knowledge_versions_hash', table_name='knowledge_document_versions')
    op.drop_table('knowledge_document_versions')
    op.drop_index('uq_knowledge_documents_name', table_name='knowledge_documents', sqlite_where=sa.text("status = 'active'"), postgresql_where=sa.text("status = 'active'"))
    op.drop_index('ix_knowledge_documents_kb', table_name='knowledge_documents')
    op.drop_table('knowledge_documents')
    op.drop_index('uq_knowledge_bases_name', table_name='knowledge_bases', sqlite_where=sa.text("status = 'active'"), postgresql_where=sa.text("status = 'active'"))
    op.drop_index('ix_knowledge_bases_tenant', table_name='knowledge_bases')
    op.drop_table('knowledge_bases')
    op.drop_table('vector_stores')
    op.drop_table('storage_backends')
    op.drop_index('ix_knowledge_jobs_due', table_name='knowledge_jobs')
    op.drop_table('knowledge_jobs')
