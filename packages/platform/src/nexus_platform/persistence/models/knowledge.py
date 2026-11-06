"""SQLAlchemy knowledge mappings (openspec 2026-11-06-knowledge-base K1.3).

The platform database is the source of truth for knowledge bases, documents, immutable document versions,
chunk text and positions, and jobs. Vectors and keyword postings are derived data kept by the vector store
the knowledge base selected (``vector_stores``, or the builtin SQLite store when ``vector_store_id`` is
NULL); they can be rebuilt from ``knowledge_chunks``.

Visibility rules the search relies on:
- only ``knowledge_bases.status = 'active'`` and ``knowledge_documents.status = 'active'`` are searchable;
- a document is searched only through ``current_version_id``, which moves to a new version in the same
  transaction that marks it ``ready`` (a version is never visible half indexed).

``settings`` keeps the WeKnora configuration blocks of later stages (FAQ, Wiki, graph extraction, parser
rules, image processing, tags...) as submitted, so the editor round-trips them before they are implemented.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (JSON, BigInteger, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text,
                        UniqueConstraint, Uuid, text)
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base


class VectorStoreRecord(Base):
    """A registered vector store of a space. Secret fields of ``connection_config`` are stored encrypted."""

    __tablename__ = 'vector_stores'
    __table_args__ = (UniqueConstraint('tenant_id', 'name', name='uq_vector_stores_name'),)
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    engine: Mapped[str] = mapped_column(String(32), nullable=False)
    connection_config: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    index_config: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_by: Mapped[UUID] = mapped_column(ForeignKey('users.id', ondelete='RESTRICT'), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class StorageBackendRecord(Base):
    """A registered storage backend for original files. Secret fields of ``config`` are stored encrypted."""

    __tablename__ = 'storage_backends'
    __table_args__ = (UniqueConstraint('tenant_id', 'name', name='uq_storage_backends_name'),)
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_by: Mapped[UUID] = mapped_column(ForeignKey('users.id', ondelete='RESTRICT'), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class KnowledgeBaseRecord(Base):
    __tablename__ = 'knowledge_bases'
    __table_args__ = (
        CheckConstraint("status IN ('active','deleting')", name='ck_knowledge_bases_status'),
        Index('ix_knowledge_bases_tenant', 'tenant_id', 'status'),
        Index('uq_knowledge_bases_name', 'tenant_id', 'name', unique=True,
              sqlite_where=text("status = 'active'"), postgresql_where=text("status = 'active'")),
    )
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default='')
    kb_type: Mapped[str] = mapped_column(String(16), nullable=False, default='document')
    #: ``{"vector": bool, "keyword": bool, "graph": bool, "wiki": bool}`` (WeKnora IndexingStrategy).
    indexing: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    #: NULL selects the builtin SQLite store.
    vector_store_id: Mapped[UUID | None] = mapped_column(ForeignKey('vector_stores.id', ondelete='RESTRICT'))
    #: NULL selects the builtin local directory.
    storage_backend_id: Mapped[UUID | None] = mapped_column(ForeignKey('storage_backends.id', ondelete='RESTRICT'))
    embedding_model_version_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    #: Vector size of the indexed chunks; fixed by the first embedded batch, reset by a full rebuild.
    embedding_dimension: Mapped[int | None] = mapped_column(Integer)
    chunk_size: Mapped[int] = mapped_column(Integer, nullable=False, default=800)
    chunk_overlap: Mapped[int] = mapped_column(Integer, nullable=False, default=120)
    settings: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default='active')
    created_by: Mapped[UUID] = mapped_column(ForeignKey('users.id', ondelete='RESTRICT'), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class KnowledgeDocumentRecord(Base):
    __tablename__ = 'knowledge_documents'
    __table_args__ = (
        CheckConstraint("status IN ('active','deleting')", name='ck_knowledge_documents_status'),
        Index('ix_knowledge_documents_kb', 'kb_id', 'status'),
        Index('uq_knowledge_documents_name', 'kb_id', 'filename', unique=True,
              sqlite_where=text("status = 'active'"), postgresql_where=text("status = 'active'")),
    )
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False)
    kb_id: Mapped[UUID] = mapped_column(ForeignKey('knowledge_bases.id', ondelete='CASCADE'), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    #: The searchable version; NULL until the first version is ready.
    current_version_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    #: Newest uploaded version (may still be indexing or failed).
    latest_version_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    status: Mapped[str] = mapped_column(String(16), nullable=False, default='active')
    created_by: Mapped[UUID] = mapped_column(ForeignKey('users.id', ondelete='RESTRICT'), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class KnowledgeDocumentVersionRecord(Base):
    """Immutable upload of a document. ``state``: pending → parsed → embedded → ready, or failed."""

    __tablename__ = 'knowledge_document_versions'
    __table_args__ = (
        UniqueConstraint('document_id', 'version', name='uq_knowledge_versions_number'),
        Index('ix_knowledge_versions_hash', 'kb_id', 'content_hash'),
        CheckConstraint("state IN ('pending','parsed','embedded','ready','failed','superseded')",
                        name='ck_knowledge_versions_state'),
    )
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False)
    kb_id: Mapped[UUID] = mapped_column(ForeignKey('knowledge_bases.id', ondelete='CASCADE'), nullable=False)
    document_id: Mapped[UUID] = mapped_column(ForeignKey('knowledge_documents.id', ondelete='CASCADE'), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    blob_key: Mapped[str] = mapped_column(String(512), nullable=False)
    size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    mime: Mapped[str] = mapped_column(String(128), nullable=False, default='')
    state: Mapped[str] = mapped_column(String(16), nullable=False, default='pending')
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: Chunks whose vectors (or keyword rows) are already in the vector store; resumes the embed stage.
    indexed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[UUID] = mapped_column(ForeignKey('users.id', ondelete='RESTRICT'), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class KnowledgeChunkRecord(Base):
    __tablename__ = 'knowledge_chunks'
    __table_args__ = (UniqueConstraint('version_id', 'ordinal', name='uq_knowledge_chunks_ordinal'),)
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    kb_id: Mapped[UUID] = mapped_column(ForeignKey('knowledge_bases.id', ondelete='CASCADE'), nullable=False)
    version_id: Mapped[UUID] = mapped_column(ForeignKey('knowledge_document_versions.id', ondelete='CASCADE'),
                                             nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    page: Mapped[int | None] = mapped_column(Integer)
    section: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    char_start: Mapped[int] = mapped_column(Integer, nullable=False)
    char_end: Mapped[int] = mapped_column(Integer, nullable=False)


class KnowledgeJobRecord(Base):
    """Resumable background work. ``kind``: ``index`` (one version) or ``cleanup`` (a deleted document or base).

    Each stage commits with its effects, so a crash resumes at the last committed stage; failures back off
    (``available_at``) and stop after the retry limit with ``state='failed'``.
    """

    __tablename__ = 'knowledge_jobs'
    __table_args__ = (
        CheckConstraint("kind IN ('index','cleanup')", name='ck_knowledge_jobs_kind'),
        CheckConstraint("state IN ('pending','done','failed','cancelled')", name='ck_knowledge_jobs_state'),
        Index('ix_knowledge_jobs_due', 'state', 'available_at'),
    )
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False)
    kb_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    document_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    version_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default='pending')
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


__all__ = ['VectorStoreRecord', 'StorageBackendRecord', 'KnowledgeBaseRecord', 'KnowledgeDocumentRecord',
           'KnowledgeDocumentVersionRecord', 'KnowledgeChunkRecord', 'KnowledgeJobRecord']
