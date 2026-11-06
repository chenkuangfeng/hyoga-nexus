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

from sqlalchemy import (JSON, BigInteger, Boolean, CheckConstraint, DateTime, Float, ForeignKey, Index, Integer, String, Text,
                        UniqueConstraint, Uuid, text, true)
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
    #: Parent chunk of a child (parent-child chunking). Children are what search matches; parents hold the text
    #: returned to the model. NULL for parents and for ordinary chunks.
    parent_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    #: False for parents of a parent-child split: stored and readable, not embedded and not searched.
    indexed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())


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
           'KnowledgeDocumentVersionRecord', 'KnowledgeChunkRecord', 'KnowledgeJobRecord', 'GraphStoreRecord',
           'GraphBuildRecord', 'GraphEntityRecord', 'GraphRelationRecord', 'GraphCommunityRecord',
           'GraphExtractionCacheRecord', 'FaqEntryRecord']


# ---------------------------------------------------------------- graph (openspec 2026-11-06-knowledge-base K2)

class GraphStoreRecord(Base):
    """A registered graph store of a space (``builtin`` rows live in the tables below; ``neo4j`` is external).

    Secret fields of ``connection_config`` are stored encrypted, like vector stores.
    """

    __tablename__ = 'graph_stores'
    __table_args__ = (UniqueConstraint('tenant_id', 'name', name='uq_graph_stores_name'),)
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    engine: Mapped[str] = mapped_column(String(32), nullable=False)
    connection_config: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_by: Mapped[UUID] = mapped_column(ForeignKey('users.id', ondelete='RESTRICT'), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class GraphBuildRecord(Base):
    """One graph build of a knowledge base; also the resumable job that produces it.

    ``state``: pending → running → ready (the newest ready build is the visible one), or failed. A build is
    never visible before it is ready; the previous ready build stays searchable until then. ``stage`` and
    ``progress`` report where a running build is (``extract`` n/total chunks, ``merge``, ``communities``,
    ``reports``, ``index``).
    """

    __tablename__ = 'knowledge_graph_builds'
    __table_args__ = (
        CheckConstraint("state IN ('pending','running','ready','failed','superseded','cancelled')",
                        name='ck_graph_builds_state'),
        Index('ix_graph_builds_kb', 'kb_id', 'state'),
        Index('ix_graph_builds_due', 'state', 'available_at'),
    )
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False)
    kb_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    mode: Mapped[str] = mapped_column(String(24), nullable=False)
    store: Mapped[str] = mapped_column(String(36), nullable=False, default='builtin')
    state: Mapped[str] = mapped_column(String(16), nullable=False, default='pending')
    stage: Mapped[str] = mapped_column(String(16), nullable=False, default='')
    progress: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    #: Document versions the build covers; elements are visible only through versions still current.
    version_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    entity_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    relation_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    community_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_by: Mapped[UUID] = mapped_column(ForeignKey('users.id', ondelete='RESTRICT'), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class GraphEntityRecord(Base):
    __tablename__ = 'knowledge_graph_entities'
    __table_args__ = (Index('ix_graph_entities_build', 'build_id'),)
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    build_id: Mapped[UUID] = mapped_column(ForeignKey('knowledge_graph_builds.id', ondelete='CASCADE'), nullable=False)
    kb_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    norm: Mapped[str] = mapped_column(String(255), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False, default='')
    description: Mapped[str] = mapped_column(Text, nullable=False, default='')
    #: ``[{"chunk_id", "version_id"}]`` where the entity was extracted.
    sources: Mapped[list[dict[str, str]]] = mapped_column(JSON, nullable=False, default=list)
    degree: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class GraphRelationRecord(Base):
    __tablename__ = 'knowledge_graph_relations'
    __table_args__ = (Index('ix_graph_relations_build', 'build_id'),)
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    build_id: Mapped[UUID] = mapped_column(ForeignKey('knowledge_graph_builds.id', ondelete='CASCADE'), nullable=False)
    kb_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    source_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    target_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default='')
    keywords: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    weight: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    sources: Mapped[list[dict[str, str]]] = mapped_column(JSON, nullable=False, default=list)


class GraphCommunityRecord(Base):
    """A community of entities (``graphrag_general``) with its report."""

    __tablename__ = 'knowledge_graph_communities'
    __table_args__ = (Index('ix_graph_communities_build', 'build_id'),)
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    build_id: Mapped[UUID] = mapped_column(ForeignKey('knowledge_graph_builds.id', ondelete='CASCADE'), nullable=False)
    kb_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    level: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    entity_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    title: Mapped[str] = mapped_column(String(255), nullable=False, default='')
    summary: Mapped[str] = mapped_column(Text, nullable=False, default='')
    sources: Mapped[list[dict[str, str]]] = mapped_column(JSON, nullable=False, default=list)


class GraphExtractionCacheRecord(Base):
    """Extraction result of one chunk text under one schema and model, reused by later builds."""

    __tablename__ = 'knowledge_graph_extractions'
    __table_args__ = (UniqueConstraint('kb_id', 'cache_key', name='uq_graph_extraction_key'),)
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    kb_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    cache_key: Mapped[str] = mapped_column(String(64), nullable=False)
    result: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


# ---------------------------------------------------------------- FAQ (openspec 2026-11-06-knowledge-base K3)

class FaqEntryRecord(Base):
    """One FAQ entry of a ``faq`` knowledge base (WeKnora ``FAQChunkMetadata``).

    Searched through the base's vector store with the entry id as the index "version": an entry is searchable
    only while ``status='active'``, ``enabled`` and ``index_state='ready'``. An edit sets ``index_state`` back to
    ``pending``; the worker re-embeds it and the old index rows are replaced, so a stale answer is never served
    from a half-updated entry (the entry leaves search until it is indexed again).
    """

    __tablename__ = 'knowledge_faq_entries'
    __table_args__ = (
        CheckConstraint("status IN ('active','deleting')", name='ck_faq_entries_status'),
        CheckConstraint("index_state IN ('pending','ready','failed')", name='ck_faq_entries_index_state'),
        Index('ix_faq_entries_kb', 'kb_id', 'status', 'enabled'),
        Index('ix_faq_entries_pending', 'index_state', 'status'),
    )
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False)
    kb_id: Mapped[UUID] = mapped_column(ForeignKey('knowledge_bases.id', ondelete='CASCADE'), nullable=False)
    category: Mapped[str] = mapped_column(String(160), nullable=False, default='')
    standard_question: Mapped[str] = mapped_column(Text, nullable=False)
    #: Normalized standard question; unique per base among active entries.
    question_key: Mapped[str] = mapped_column(String(255), nullable=False)
    similar_questions: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    negative_questions: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    answers: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    #: ``all`` returns every answer, ``first`` only the first one.
    answer_strategy: Mapped[str] = mapped_column(String(16), nullable=False, default='all')
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    recommended: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default='active')
    index_state: Mapped[str] = mapped_column(String(16), nullable=False, default='pending')
    index_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    index_error: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[UUID] = mapped_column(ForeignKey('users.id', ondelete='RESTRICT'), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
