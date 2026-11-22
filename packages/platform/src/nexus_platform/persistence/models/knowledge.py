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

from sqlalchemy import (JSON, BigInteger, Boolean, CheckConstraint, DateTime, Float, ForeignKey, ForeignKeyConstraint, Index, Integer, String, Text,
                        UniqueConstraint, Uuid, false, text, true)
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
        CheckConstraint("ownership IN ('personal','enterprise')", name='ck_knowledge_bases_ownership'),
        CheckConstraint("visibility IN ('private','tenant','scoped')", name='ck_knowledge_bases_visibility'),
        UniqueConstraint('id', 'tenant_id', name='uq_knowledge_bases_id_tenant'),
        Index('ix_knowledge_bases_tenant', 'tenant_id', 'status'),
        Index('uq_knowledge_bases_name', 'tenant_id', 'name', unique=True,
              sqlite_where=text("status = 'active'"), postgresql_where=text("status = 'active'")),
    )
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default='')
    kb_type: Mapped[str] = mapped_column(String(16), nullable=False, default='document')
    #: ``personal`` (maintained by its creator) or ``enterprise`` (managed by holders of ``enterprise_kbs:manage``;
    #: content also by the members in ``knowledge_base_maintainers``). openspec 2026-11-11-enterprise-saas decision 2.
    ownership: Mapped[str] = mapped_column(String(16), nullable=False, default='personal')
    #: ``private``: only its managers and maintainers (plus the enterprise's owners and admins) read it;
    #: ``tenant``: every member of the enterprise reads it (openspec 2026-11-11-enterprise-saas decision 3).
    visibility: Mapped[str] = mapped_column(String(16), nullable=False, default='private')
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
    #: Pinned bases are listed first (WeKnora ``is_pinned``).
    pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    pinned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[UUID] = mapped_column(ForeignKey('users.id', ondelete='RESTRICT'), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class KnowledgeBaseMaintainerRecord(Base):
    """A member who may maintain the content of an enterprise knowledge base (documents, chunks, FAQ entries).

    Only meaningful for ``ownership = 'enterprise'``; settings, visibility, deletion and sharing stay with
    ``enterprise_kbs:manage``. The composite keys keep the base and the member inside one enterprise.
    """
    __tablename__ = 'knowledge_base_maintainers'
    __table_args__ = (
        ForeignKeyConstraint(['kb_id', 'tenant_id'], ['knowledge_bases.id', 'knowledge_bases.tenant_id'],
                             ondelete='CASCADE', name='fk_kb_maintainers_kb_tenant'),
        ForeignKeyConstraint(['tenant_id', 'user_id'], ['tenant_memberships.tenant_id', 'tenant_memberships.user_id'],
                             ondelete='CASCADE', name='fk_kb_maintainers_membership'),
        Index('ix_kb_maintainers_user', 'tenant_id', 'user_id'),
    )
    kb_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    granted_by: Mapped[UUID] = mapped_column(ForeignKey('users.id', ondelete='RESTRICT'), nullable=False)
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class KnowledgeFolderRecord(Base):
    """An explicit directory in a knowledge base, including empty directories."""

    __tablename__ = 'knowledge_folders'
    kb_id: Mapped[UUID] = mapped_column(ForeignKey('knowledge_bases.id', ondelete='CASCADE'), primary_key=True)
    path: Mapped[str] = mapped_column(String(1024), primary_key=True)


class KnowledgeDocumentRecord(Base):
    __tablename__ = 'knowledge_documents'
    __table_args__ = (
        CheckConstraint("status IN ('active','deleting')", name='ck_knowledge_documents_status'),
        Index('ix_knowledge_documents_kb', 'kb_id', 'status'),
        Index('uq_knowledge_documents_name', 'kb_id', 'folder_path', 'filename', unique=True,
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
    #: Organization (K5): tags of the base, a folder path such as ``docs/spec`` ('' = top level) and free metadata
    #: that search can filter on.
    tag_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    folder_path: Mapped[str] = mapped_column(String(1024), nullable=False, default='', server_default='')
    custom_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
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
    #: Document summary written by the model (K5.2); NULL until generated or when summaries are off.
    summary: Mapped[str | None] = mapped_column(Text)
    #: Which enrichments ran for this version: ``{"summary": "done", "questions": "done", "tags": "done"}``.
    enrichment: Mapped[dict[str, str]] = mapped_column(JSON, nullable=False, default=dict)
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
    #: Questions the model wrote for this chunk (K5.2); each is an extra index row that resolves back to the chunk.
    questions: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)


class KnowledgeJobRecord(Base):
    """Resumable background work. ``kind``: ``index`` (one version), ``cleanup`` (a deleted document or base), ``enrich`` or ``wiki`` (synthesis of a
    ready version, or retraction of a deleted document when ``version_id`` is NULL).

    Each stage commits with its effects, so a crash resumes at the last committed stage; failures back off
    (``available_at``) and stop after the retry limit with ``state='failed'``.
    """

    __tablename__ = 'knowledge_jobs'
    __table_args__ = (
        CheckConstraint("kind IN ('index','cleanup','enrich','wiki')", name='ck_knowledge_jobs_kind'),
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
           'GraphExtractionCacheRecord', 'FaqEntryRecord', 'KnowledgeTagRecord', 'ParserEngineConfigRecord']


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
    #: Tag of the base (K5); ``category`` keeps the free-text label from CSV imports.
    tag_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
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


class KnowledgeTagRecord(Base):
    """A tag of one knowledge base (WeKnora ``KnowledgeTag``): documents and FAQ entries are grouped by it."""

    __tablename__ = 'knowledge_tags'
    __table_args__ = (UniqueConstraint('kb_id', 'name', name='uq_knowledge_tags_name'),)
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False)
    kb_id: Mapped[UUID] = mapped_column(ForeignKey('knowledge_bases.id', ondelete='CASCADE'), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    color: Mapped[str] = mapped_column(String(32), nullable=False, default='')
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_by: Mapped[UUID] = mapped_column(ForeignKey('users.id', ondelete='RESTRICT'), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ParserEngineConfigRecord(Base):
    """Connection settings of the external parser engines of a space (WeKnora ``parser-engine-config``).

    Secrets (`mineru_api_key`, `mineru_server_api_key`, `paddleocr_vl_cloud_token`) are encrypted with the
    deployment key, bound to the space id, and masked when read.
    """

    __tablename__ = 'knowledge_parser_configs'
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey('tenants.id', ondelete='CASCADE'), primary_key=True)
    config: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    updated_by: Mapped[UUID] = mapped_column(ForeignKey('users.id', ondelete='RESTRICT'), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class WikiPageRecord(Base):
    """One page of a wiki knowledge base (WeKnora ``WikiPage``).

    Pages are searched through the base's vector store with the page id as the index "version" (like FAQ entries):
    a page is searchable only while ``status='published'`` and ``index_state='ready'``. Every edit bumps
    ``version`` (optimistic lock) and snapshots the previous state in ``knowledge_wiki_revisions``.
    ``source_refs`` lists the document ids the page was synthesized from; ``in_links``/``out_links`` are derived
    from the ``[[slug]]`` links of ``content`` and rebuilt on every write.
    """

    __tablename__ = 'knowledge_wiki_pages'
    __table_args__ = (
        UniqueConstraint('kb_id', 'slug', name='uq_wiki_pages_slug'),
        CheckConstraint("status IN ('published','draft','archived','deleting')", name='ck_wiki_pages_status'),
        CheckConstraint("index_state IN ('pending','ready','failed')", name='ck_wiki_pages_index_state'),
        Index('ix_wiki_pages_kb', 'kb_id', 'status', 'page_type'),
        Index('ix_wiki_pages_pending', 'index_state', 'status'),
    )
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False)
    kb_id: Mapped[UUID] = mapped_column(ForeignKey('knowledge_bases.id', ondelete='CASCADE'), nullable=False)
    slug: Mapped[str] = mapped_column(String(200), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    page_type: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default='published')
    content: Mapped[str] = mapped_column(Text, nullable=False, default='')
    summary: Mapped[str] = mapped_column(Text, nullable=False, default='')
    aliases: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    folder_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    category_path: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source_refs: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    in_links: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    out_links: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    page_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    #: ``pipeline`` | ``agent`` | ``user`` | ``revert`` — author kind of the current version.
    last_edit_source: Mapped[str] = mapped_column(String(16), nullable=False, default='pipeline')
    last_editor_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    index_state: Mapped[str] = mapped_column(String(16), nullable=False, default='pending')
    index_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    index_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class WikiRevisionRecord(Base):
    """Immutable snapshot of a superseded wiki page version (WeKnora ``WikiPageRevision``)."""

    __tablename__ = 'knowledge_wiki_revisions'
    __table_args__ = (UniqueConstraint('page_id', 'version', name='uq_wiki_revisions_version'),)
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False)
    kb_id: Mapped[UUID] = mapped_column(ForeignKey('knowledge_bases.id', ondelete='CASCADE'), nullable=False)
    page_id: Mapped[UUID] = mapped_column(ForeignKey('knowledge_wiki_pages.id', ondelete='CASCADE'), nullable=False)
    slug: Mapped[str] = mapped_column(String(200), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    page_type: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, default='')
    summary: Mapped[str] = mapped_column(Text, nullable=False, default='')
    aliases: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    edit_source: Mapped[str] = mapped_column(String(16), nullable=False, default='pipeline')
    editor_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    edited_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class WikiFolderRecord(Base):
    """A directory node of a wiki base (WeKnora ``WikiFolder``); ``path`` is ``a/b`` from the root."""

    __tablename__ = 'knowledge_wiki_folders'
    __table_args__ = (UniqueConstraint('kb_id', 'path', name='uq_wiki_folders_path'),)
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False)
    kb_id: Mapped[UUID] = mapped_column(ForeignKey('knowledge_bases.id', ondelete='CASCADE'), nullable=False)
    parent_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    path: Mapped[str] = mapped_column(String(500), nullable=False)
    depth: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class WikiIssueRecord(Base):
    """A quality issue reported on a wiki page by lint or by an agent (WeKnora ``WikiPageIssue``)."""

    __tablename__ = 'knowledge_wiki_issues'
    __table_args__ = (
        CheckConstraint("status IN ('pending','resolved','ignored')", name='ck_wiki_issues_status'),
        Index('ix_wiki_issues_kb', 'kb_id', 'status'),
    )
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False)
    kb_id: Mapped[UUID] = mapped_column(ForeignKey('knowledge_bases.id', ondelete='CASCADE'), nullable=False)
    slug: Mapped[str] = mapped_column(String(200), nullable=False)
    issue_type: Mapped[str] = mapped_column(String(32), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default='')
    suspected_knowledge_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default='pending')
    reported_by: Mapped[str] = mapped_column(String(32), nullable=False, default='lint')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
