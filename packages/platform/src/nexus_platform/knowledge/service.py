"""Knowledge bases and documents (openspec 2026-11-06-knowledge-base K1.4).

Every function runs inside the caller's transaction (``with db.begin():`` in the API layer) and checks access
with :mod:`.access`. Blob writes happen before the database rows are committed: a failed commit leaves an
orphan file under an unused key (harmless, removed by cleanup), never a row pointing at a missing file.

Lifecycle summary:
- upload: SHA-256 of the bytes; the same hash already present in the base returns that document
  (``deduplicated``). Otherwise the file is stored, a new document (or a new version of the document with
  the same filename) is created as ``pending`` and an ``index`` job is queued. The previous version stays
  current and searchable until the new one is ``ready``.
- delete: the document or base is marked ``deleting`` (invisible to every search at once) and a ``cleanup``
  job removes index rows, chunks, versions and files.
"""
from __future__ import annotations

import hashlib
import mimetypes
from typing import Any, Sequence
from uuid import UUID

from datetime import timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from nexus_core.platform import new_id, utc_now
from nexus_knowledge import capabilities
from nexus_knowledge.ingest.chunk import ChunkConfig
from nexus_knowledge.ingest.parse import SUPPORTED_SUFFIXES, suffix_of
from nexus_platform.authz.audit import audit
from nexus_platform.authz.resources import register_resource, deactivate_resource
from nexus_platform.errors import Conflict, NotFound
from nexus_platform.identity.service import require_membership
from nexus_platform.persistence.models import (KnowledgeBaseRecord, KnowledgeChunkRecord, KnowledgeDocumentRecord,
                                               KnowledgeDocumentVersionRecord, KnowledgeJobRecord, UserRecord)
from . import access, stores
from nexus_knowledge.retrieval import synonyms as synonym_rules
from .graph import config as graph_config
from . import faq as faq_rules

KB_TYPES = ('document', 'faq', 'wiki')
INDEXING_KEYS = ('vector', 'keyword', 'graph', 'wiki')
DEFAULT_INDEXING = {'vector': True, 'keyword': True, 'graph': False, 'wiki': False}


# ---------------------------------------------------------------- views

def base_view(db: Session, kb: KnowledgeBaseRecord, tenant_id: UUID, user_id: UUID) -> dict[str, Any]:
    counts = db.execute(select(func.count(KnowledgeDocumentRecord.id)).where(
        KnowledgeDocumentRecord.kb_id == kb.id, KnowledgeDocumentRecord.status == 'active')).scalar_one()
    if kb.kb_type == 'faq':  # entries are the "documents" of a FAQ base
        from nexus_platform.persistence.models import FaqEntryRecord
        counts = db.execute(select(func.count(FaqEntryRecord.id)).where(
            FaqEntryRecord.kb_id == kb.id, FaqEntryRecord.status == 'active')).scalar_one()
    processing = db.execute(select(func.count(KnowledgeDocumentVersionRecord.id)).where(
        KnowledgeDocumentVersionRecord.kb_id == kb.id,
        KnowledgeDocumentVersionRecord.state.in_(('pending', 'parsed', 'embedded')))).scalar_one()
    chunks = db.execute(select(func.count(KnowledgeChunkRecord.id)).join(
        KnowledgeDocumentRecord, KnowledgeDocumentRecord.current_version_id == KnowledgeChunkRecord.version_id).where(
        KnowledgeDocumentRecord.kb_id == kb.id, KnowledgeDocumentRecord.status == 'active',
        KnowledgeChunkRecord.parent_id.is_(None))).scalar_one()
    creator = db.get(UserRecord, kb.created_by)
    return {
        'id': str(kb.id), 'tenant_id': str(kb.tenant_id), 'name': kb.name, 'description': kb.description,
        'type': kb.kb_type, 'indexing_strategy': {key: bool(kb.indexing.get(key)) for key in INDEXING_KEYS},
        'vector_store_id': str(kb.vector_store_id) if kb.vector_store_id else stores.BUILTIN,
        'vector_engine': stores.engine_of(db, kb),
        'storage_backend_id': str(kb.storage_backend_id) if kb.storage_backend_id else stores.BUILTIN,
        'embedding_model_id': str(kb.embedding_model_version_id) if kb.embedding_model_version_id else None,
        'embedding_dimension': kb.embedding_dimension,
        'chunking_config': {'chunk_size': kb.chunk_size, 'chunk_overlap': kb.chunk_overlap},
        'settings': dict(kb.settings), 'shared': kb.tenant_id != tenant_id,
        'can_edit': kb.tenant_id == tenant_id and access.can_write(db, kb, user_id),
        'knowledge_count': counts, 'chunk_count': chunks, 'processing_count': processing,
        'is_processing': processing > 0, 'creator_id': str(kb.created_by),
        'creator_name': getattr(creator, 'display_name', None) or '',
        'is_pinned': bool(kb.pinned), 'pinned_at': kb.pinned_at.isoformat() if kb.pinned_at else None,
        'created_at': kb.created_at.isoformat(), 'updated_at': kb.updated_at.isoformat(),
    }


def version_view(version: KnowledgeDocumentVersionRecord) -> dict[str, Any]:
    return {'id': str(version.id), 'version': version.version, 'state': version.state, 'size': version.size,
            'mime': version.mime, 'content_hash': version.content_hash, 'chunk_count': version.chunk_count,
            'indexed_count': version.indexed_count, 'error_code': version.error_code,
            'error_message': version.error_message, 'created_at': version.created_at.isoformat(),
            'updated_at': version.updated_at.isoformat()}


def document_view(db: Session, doc: KnowledgeDocumentRecord) -> dict[str, Any]:
    latest = db.get(KnowledgeDocumentVersionRecord, doc.latest_version_id) if doc.latest_version_id else None
    current = db.get(KnowledgeDocumentVersionRecord, doc.current_version_id) if doc.current_version_id else None
    return {'id': str(doc.id), 'kb_id': str(doc.kb_id), 'filename': doc.filename, 'status': doc.status,
            'current_version': version_view(current) if current else None,
            'latest_version': version_view(latest) if latest else None,
            'parse_status': _parse_status(latest), 'file_type': suffix_of(doc.filename).lstrip('.'),
            'tag_ids': list(doc.tag_ids or []), 'folder_path': doc.folder_path or '',
            'custom_metadata': dict(doc.custom_metadata or {}),
            'created_at': doc.created_at.isoformat(), 'updated_at': doc.updated_at.isoformat()}


def _parse_status(version: KnowledgeDocumentVersionRecord | None) -> str:
    """WeKnora's ``parse_status`` vocabulary for the copied document list."""
    if version is None:
        return 'pending'
    return {'pending': 'pending', 'parsed': 'processing', 'embedded': 'processing', 'ready': 'completed',
            'failed': 'failed', 'superseded': 'completed'}[version.state]


# ---------------------------------------------------------------- knowledge bases

def _check_settings(db: Session, tenant_id: UUID, *, kb_type: str, indexing: dict[str, Any],
                    vector_store_id: str | None, storage_backend_id: str | None,
                    embedding_model_id: UUID | None, chunk_size: int, chunk_overlap: int,
                    settings: dict[str, Any] | None = None, user_id: UUID | None = None):
    if kb_type not in KB_TYPES:
        raise ValueError(f'type must be one of {", ".join(KB_TYPES)}')
    capabilities.require_available('kb_type', kb_type)
    normalized = {key: bool(indexing.get(key, DEFAULT_INDEXING[key])) for key in INDEXING_KEYS}
    for key, enabled in normalized.items():
        if enabled:
            capabilities.require_available('indexing', key)
    if not (normalized['vector'] or normalized['keyword']):
        raise ValueError('enable vector or keyword indexing')
    if kb_type == 'faq':
        if normalized['graph'] or normalized['wiki']:
            raise ValueError('FAQ knowledge bases index questions and answers only (no graph or wiki)')
        faq_rules.validate_config(settings)
    if normalized['graph']:
        # Graph building calls a chat model with the creator's key (decision 6) and needs a valid configuration.
        config = graph_config.parse(settings)
        if config.store != 'builtin':
            from nexus_platform.persistence.models import GraphStoreRecord
            try:
                row = db.get(GraphStoreRecord, UUID(config.store))
            except ValueError:
                row = None
            if row is None or row.tenant_id != tenant_id:
                raise NotFound('Graph store not found')
        if user_id is not None:
            _authorize_chat_model(db, tenant_id, user_id, config.model_id)
    ChunkConfig.from_settings(chunk_size, chunk_overlap, (settings or {}).get('chunking_config'))
    synonym_rules.parse((settings or {}).get('synonyms'))  # rejects malformed synonym groups
    for rule in ((settings or {}).get('chunking_config') or {}).get('parser_engine_rules') or []:
        if isinstance(rule, dict) and rule.get('engine'):
            capabilities.require_available('parser_engine', str(rule['engine']))  # external engines are planned
    store = stores.vector_store_of_tenant(db, tenant_id, vector_store_id)
    backend = stores.storage_backend_of_tenant(db, tenant_id, storage_backend_id)
    if normalized['vector'] and embedding_model_id is None:
        raise ValueError('vector indexing needs an embedding model')
    engine = store.engine if store else 'sqlite'
    from nexus_knowledge.index import FACTORIES
    factory = FACTORIES.get(engine)
    if getattr(factory, 'requires_vectors', False) and not normalized['vector']:
        raise ValueError(f'{engine} stores need vector indexing with an embedding model')
    return normalized, store, backend


def create_base(db: Session, tenant_id: UUID, user_id: UUID, *, name: str, description: str = '',
                kb_type: str = 'document', indexing: dict[str, Any] | None = None, vector_store_id: str | None = None,
                storage_backend_id: str | None = None, embedding_model_id: UUID | None = None,
                chunk_size: int = 800, chunk_overlap: int = 120, settings: dict[str, Any] | None = None
                ) -> KnowledgeBaseRecord:
    require_membership(db, tenant_id, user_id)
    name = (name or '').strip()
    if not name or len(name) > 160:
        raise ValueError('name must be 1-160 characters')
    normalized, store, backend = _check_settings(
        db, tenant_id, kb_type=kb_type, indexing=indexing or {}, vector_store_id=vector_store_id,
        storage_backend_id=storage_backend_id, embedding_model_id=embedding_model_id, chunk_size=chunk_size,
        chunk_overlap=chunk_overlap, settings=settings, user_id=user_id)
    if embedding_model_id is not None:
        _authorize_embedding(db, tenant_id, user_id, embedding_model_id)
    _unique_name(db, tenant_id, name)
    now = utc_now()
    kb = KnowledgeBaseRecord(
        id=new_id(), tenant_id=tenant_id, name=name, description=(description or '')[:2000], kb_type=kb_type,
        indexing=normalized, vector_store_id=store.id if store else None,
        storage_backend_id=backend.id if backend else None, embedding_model_version_id=embedding_model_id,
        chunk_size=chunk_size, chunk_overlap=chunk_overlap, settings=dict(settings or {}), status='active',
        created_by=user_id, created_at=now, updated_at=now)
    db.add(kb)
    db.flush()
    register_resource(db, tenant_id=tenant_id, kind=access.KIND, resource_id=str(kb.id), version_id=None)
    audit(db, tenant_id, user_id, 'knowledge_base.created', access.KIND, str(kb.id),
          {'type': kb_type, 'engine': store.engine if store else 'sqlite'})
    return kb


def _unique_name(db: Session, tenant_id: UUID, name: str, exclude: UUID | None = None) -> None:
    query = select(KnowledgeBaseRecord.id).where(KnowledgeBaseRecord.tenant_id == tenant_id,
                                                 KnowledgeBaseRecord.name == name,
                                                 KnowledgeBaseRecord.status == 'active')
    if exclude is not None:
        query = query.where(KnowledgeBaseRecord.id != exclude)
    if db.scalar(query) is not None:
        raise Conflict('A knowledge base with this name already exists')


def _authorize_chat_model(db: Session, tenant_id: UUID, user_id: UUID, version_id: UUID) -> None:
    from nexus_platform.models.provider_settings import authorize_model
    from nexus_platform.persistence.models import ModelProfileRecord

    version = authorize_model(db, tenant_id, user_id, version_id)
    profile = db.get(ModelProfileRecord, version.profile_id)
    if profile is None or profile.model_type != 'chat':
        raise ValueError('graph.model_id must be a chat model')


def _authorize_embedding(db: Session, tenant_id: UUID, user_id: UUID, version_id: UUID) -> None:
    """The creator must be able to use the embedding model: indexing runs with the creator's key (decision 6)."""
    from nexus_platform.models.provider_settings import authorize_model
    from nexus_platform.persistence.models import ModelProfileRecord

    version = authorize_model(db, tenant_id, user_id, version_id)
    profile = db.get(ModelProfileRecord, version.profile_id)
    if profile is None or profile.model_type != 'embedding':
        raise ValueError('embedding_model_id must be an embedding model')


def update_base(db: Session, tenant_id: UUID, user_id: UUID, kb_id: UUID, changes: dict[str, Any]
                ) -> KnowledgeBaseRecord:
    """Change name, description, settings and chunking; the vector store and storage backend are fixed.

    Changing the embedding model or chunking does not rebuild existing documents by itself; ``rebuild_base``
    re-indexes every document (a full rebuild also resets the embedding dimension).
    """
    kb = access.writable_base(db, kb_id, tenant_id, user_id)
    if 'name' in changes:
        name = (changes['name'] or '').strip()
        if not name or len(name) > 160:
            raise ValueError('name must be 1-160 characters')
        _unique_name(db, tenant_id, name, exclude=kb.id)
        kb.name = name
    if 'description' in changes:
        kb.description = (changes['description'] or '')[:2000]
    if 'vector_store_id' in changes and (changes['vector_store_id'] or stores.BUILTIN) != (
            str(kb.vector_store_id) if kb.vector_store_id else stores.BUILTIN):
        raise Conflict('The vector store of a knowledge base cannot change')
    if 'storage_backend_id' in changes and (changes['storage_backend_id'] or stores.BUILTIN) != (
            str(kb.storage_backend_id) if kb.storage_backend_id else stores.BUILTIN):
        raise Conflict('The storage backend of a knowledge base cannot change')
    if 'type' in changes and changes['type'] != kb.kb_type:
        raise Conflict('The type of a knowledge base cannot change')
    embedding = changes.get('embedding_model_id', kb.embedding_model_version_id)
    embedding = UUID(str(embedding)) if embedding else None
    if embedding != kb.embedding_model_version_id and embedding is not None:
        _authorize_embedding(db, tenant_id, user_id, embedding)
    indexing = changes.get('indexing_strategy', kb.indexing)
    chunk = changes.get('chunking_config') or {}
    normalized, _, _ = _check_settings(
        db, tenant_id, kb_type=kb.kb_type, indexing=indexing,
        vector_store_id=str(kb.vector_store_id) if kb.vector_store_id else None,
        storage_backend_id=str(kb.storage_backend_id) if kb.storage_backend_id else None,
        embedding_model_id=embedding, chunk_size=int(chunk.get('chunk_size', kb.chunk_size)),
        chunk_overlap=int(chunk.get('chunk_overlap', kb.chunk_overlap)),
        settings=changes['settings'] if isinstance(changes.get('settings'), dict) else kb.settings, user_id=user_id)
    graph_changed = normalized.get('graph') != bool(kb.indexing.get('graph')) or (
        isinstance(changes.get('settings'), dict) and changes['settings'].get('graph') != kb.settings.get('graph'))
    kb.indexing, kb.embedding_model_version_id = normalized, embedding
    kb.chunk_size = int(chunk.get('chunk_size', kb.chunk_size))
    kb.chunk_overlap = int(chunk.get('chunk_overlap', kb.chunk_overlap))
    if isinstance(changes.get('settings'), dict):
        kb.settings = dict(changes['settings'])
    kb.updated_at = utc_now()
    if graph_changed:
        from .graph.build import schedule
        schedule(db, kb, user_id, delay=timedelta(0))
    audit(db, tenant_id, user_id, 'knowledge_base.updated', access.KIND, str(kb.id), {})
    return kb


def list_bases(db: Session, tenant_id: UUID, user_id: UUID) -> list[KnowledgeBaseRecord]:
    require_membership(db, tenant_id, user_id)
    return access.readable_bases(db, tenant_id, user_id)


def delete_base(db: Session, tenant_id: UUID, user_id: UUID, kb_id: UUID) -> None:
    kb = access.writable_base(db, kb_id, tenant_id, user_id)
    kb.status, kb.updated_at = 'deleting', utc_now()
    cancel_graph_builds(db, kb.id)
    deactivate_resource(db, tenant_id=tenant_id, kind=access.KIND, resource_id=str(kb.id), version_id=None)
    _queue(db, kb, kind='cleanup')
    audit(db, tenant_id, user_id, 'knowledge_base.deleted', access.KIND, str(kb.id), {})


def rebuild_base(db: Session, tenant_id: UUID, user_id: UUID, kb_id: UUID) -> int:
    """Re-index the current or latest version of every document (new chunking, new embedding model)."""
    kb = access.writable_base(db, kb_id, tenant_id, user_id)
    kb.embedding_dimension = None
    from .graph.build import schedule
    schedule(db, kb, user_id)
    count = 0
    for doc in db.scalars(select(KnowledgeDocumentRecord).where(KnowledgeDocumentRecord.kb_id == kb.id,
                                                              KnowledgeDocumentRecord.status == 'active')):
        version_id = doc.latest_version_id or doc.current_version_id
        if version_id is not None:
            reindex_version(db, kb, db.get(KnowledgeDocumentVersionRecord, version_id), user_id)
            count += 1
    audit(db, tenant_id, user_id, 'knowledge_base.rebuilt', access.KIND, str(kb.id), {'documents': count})
    return count


# ---------------------------------------------------------------- documents

def _queue(db: Session, kb: KnowledgeBaseRecord, *, kind: str, document_id: UUID | None = None,
           version_id: UUID | None = None) -> KnowledgeJobRecord:
    now = utc_now()
    job = KnowledgeJobRecord(id=new_id(), tenant_id=kb.tenant_id, kb_id=kb.id, document_id=document_id,
                             version_id=version_id, kind=kind, state='pending', attempts=0, available_at=now,
                             created_at=now, updated_at=now)
    db.add(job)
    return job


def prepare_upload(db: Session, tenant_id: UUID, user_id: UUID, kb_id: UUID, filename: str, data: bytes,
                   max_bytes: int) -> tuple[KnowledgeBaseRecord, str, KnowledgeDocumentRecord | None]:
    """Validate an upload; returns ``(kb, sha256, duplicate_document_or_None)``. No rows are written."""
    kb = access.writable_base(db, kb_id, tenant_id, user_id)
    filename = (filename or '').strip().replace('\\', '/').rsplit('/', 1)[-1]
    if not filename or len(filename) > 255:
        raise ValueError('filename must be 1-255 characters')
    if suffix_of(filename) not in SUPPORTED_SUFFIXES:
        raise ValueError(f'unsupported document type: {suffix_of(filename) or "(none)"}; '
                         'more parser engines are planned (K4)')
    if not data:
        raise ValueError('file is empty')
    if len(data) > max_bytes:
        raise ValueError(f'file exceeds the {max_bytes // (1024 * 1024)} MB upload limit')
    digest = hashlib.sha256(data).hexdigest()
    duplicate = db.scalar(select(KnowledgeDocumentRecord).join(
        KnowledgeDocumentVersionRecord, KnowledgeDocumentVersionRecord.document_id == KnowledgeDocumentRecord.id
    ).where(KnowledgeDocumentVersionRecord.kb_id == kb.id, KnowledgeDocumentVersionRecord.content_hash == digest,
            KnowledgeDocumentVersionRecord.state != 'superseded', KnowledgeDocumentRecord.status == 'active'))
    return kb, digest, duplicate


def blob_key(kb: KnowledgeBaseRecord, document_id: UUID, version_id: UUID) -> str:
    return f'{kb.tenant_id}/{kb.id}/{document_id}/{version_id}'


def add_version(db: Session, kb: KnowledgeBaseRecord, user_id: UUID, filename: str, digest: str, size: int,
                document_id: UUID, version_id: UUID) -> tuple[KnowledgeDocumentRecord, KnowledgeDocumentVersionRecord]:
    """Create the document (or reuse the active one with this filename) and a pending version with a job.

    ``document_id``/``version_id`` are chosen by the caller before the file is stored under their key; an
    existing document with the same filename keeps its own id.
    """
    filename = filename.strip().replace('\\', '/').rsplit('/', 1)[-1]
    now = utc_now()
    doc = db.scalar(select(KnowledgeDocumentRecord).where(
        KnowledgeDocumentRecord.kb_id == kb.id, KnowledgeDocumentRecord.filename == filename,
        KnowledgeDocumentRecord.status == 'active'))
    if doc is None:
        doc = KnowledgeDocumentRecord(id=document_id, tenant_id=kb.tenant_id, kb_id=kb.id, filename=filename,
                                      status='active', created_by=user_id, created_at=now, updated_at=now)
        db.add(doc)
        db.flush()
    number = (db.scalar(select(func.max(KnowledgeDocumentVersionRecord.version)).where(
        KnowledgeDocumentVersionRecord.document_id == doc.id)) or 0) + 1
    version = KnowledgeDocumentVersionRecord(
        id=version_id, tenant_id=kb.tenant_id, kb_id=kb.id, document_id=doc.id, version=number,
        content_hash=digest, blob_key=blob_key(kb, document_id, version_id), size=size,
        mime=mimetypes.guess_type(filename)[0] or '', state='pending', created_by=user_id, created_at=now,
        updated_at=now)
    db.add(version)
    db.flush()
    doc.latest_version_id, doc.updated_at = version.id, now
    _queue(db, kb, kind='index', document_id=doc.id, version_id=version.id)
    audit(db, kb.tenant_id, user_id, 'knowledge_document.uploaded', 'knowledge_document', str(doc.id),
          {'kb_id': str(kb.id), 'version': number, 'size': size})
    return doc, version


def readable_document(db: Session, tenant_id: UUID, user_id: UUID, document_id: UUID
                      ) -> tuple[KnowledgeBaseRecord, KnowledgeDocumentRecord]:
    doc = db.get(KnowledgeDocumentRecord, document_id)
    if doc is None or doc.status != 'active':
        raise NotFound('Document not found')
    kb = access.readable_base(db, doc.kb_id, tenant_id, user_id)
    return kb, doc


def list_documents(db: Session, tenant_id: UUID, user_id: UUID, kb_id: UUID, *, keyword: str = '',
                   offset: int = 0, limit: int = 50, tag_ids: Sequence[str] = (), folder: str | None = None,
                   recursive: bool = True, file_type: str = '') -> tuple[list[KnowledgeDocumentRecord], int]:
    kb = access.readable_base(db, kb_id, tenant_id, user_id)
    query = select(KnowledgeDocumentRecord).where(KnowledgeDocumentRecord.kb_id == kb.id,
                                                  KnowledgeDocumentRecord.status == 'active')
    if keyword:
        escaped = keyword.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
        query = query.where(KnowledgeDocumentRecord.filename.ilike(f'%{escaped}%', escape='\\'))
    if folder is not None:
        path = folder.strip('/')
        like = path.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
        query = query.where(KnowledgeDocumentRecord.folder_path == path if not recursive else or_(
            KnowledgeDocumentRecord.folder_path == path,
            KnowledgeDocumentRecord.folder_path.like(f'{like}/%', escape='\\')) if path else True)
    if file_type:
        query = query.where(KnowledgeDocumentRecord.filename.ilike(f'%.{file_type.lstrip(".")}', escape='\\'))
    ordered = query.order_by(KnowledgeDocumentRecord.updated_at.desc(), KnowledgeDocumentRecord.id)
    if tag_ids:  # JSON containment differs by database; tags are few, so filter in Python
        wanted = set(tag_ids)
        matching = [d for d in db.scalars(ordered) if wanted & set(d.tag_ids or [])]
        return matching[max(0, offset):max(0, offset) + max(1, min(limit, 200))], len(matching)
    total = db.execute(select(func.count()).select_from(query.subquery())).scalar_one()
    rows = db.scalars(ordered.offset(max(0, offset)).limit(max(1, min(limit, 200)))).all()
    return list(rows), total


def list_versions(db: Session, tenant_id: UUID, user_id: UUID, document_id: UUID
                  ) -> list[KnowledgeDocumentVersionRecord]:
    _, doc = readable_document(db, tenant_id, user_id, document_id)
    return list(db.scalars(select(KnowledgeDocumentVersionRecord).where(
        KnowledgeDocumentVersionRecord.document_id == doc.id).order_by(KnowledgeDocumentVersionRecord.version.desc())))


def reindex_version(db: Session, kb: KnowledgeBaseRecord, version: KnowledgeDocumentVersionRecord,
                    user_id: UUID) -> None:
    """Reset a version to ``pending`` and queue a new index job (used by retry and rebuild)."""
    db.execute(KnowledgeChunkRecord.__table__.delete().where(KnowledgeChunkRecord.version_id == version.id))
    version.state, version.chunk_count, version.indexed_count = 'pending', 0, 0
    version.error_code = version.error_message = None
    version.updated_at = utc_now()
    for job in db.scalars(select(KnowledgeJobRecord).where(KnowledgeJobRecord.version_id == version.id,
                                                         KnowledgeJobRecord.state == 'pending')):
        job.state = 'cancelled'
    _queue(db, kb, kind='index', document_id=version.document_id, version_id=version.id)


def retry_document(db: Session, tenant_id: UUID, user_id: UUID, document_id: UUID) -> KnowledgeDocumentVersionRecord:
    kb, doc = readable_document(db, tenant_id, user_id, document_id)
    kb = access.writable_base(db, kb.id, tenant_id, user_id)
    version = db.get(KnowledgeDocumentVersionRecord, doc.latest_version_id) if doc.latest_version_id else None
    if version is None or version.state not in ('failed', 'ready'):
        raise Conflict('Only a failed or indexed version can be re-indexed')
    reindex_version(db, kb, version, user_id)
    audit(db, tenant_id, user_id, 'knowledge_document.retried', 'knowledge_document', str(doc.id), {})
    return version


def delete_document(db: Session, tenant_id: UUID, user_id: UUID, document_id: UUID) -> None:
    kb, doc = readable_document(db, tenant_id, user_id, document_id)
    kb = access.writable_base(db, kb.id, tenant_id, user_id)
    doc.status, doc.updated_at = 'deleting', utc_now()
    _queue(db, kb, kind='cleanup', document_id=doc.id)
    from .graph.build import schedule
    schedule(db, kb, user_id)
    audit(db, tenant_id, user_id, 'knowledge_document.deleted', 'knowledge_document', str(doc.id),
          {'kb_id': str(kb.id)})


def chunks_of(db: Session, tenant_id: UUID, user_id: UUID, document_id: UUID, *, offset: int = 0,
              limit: int = 50) -> tuple[list[KnowledgeChunkRecord], int]:
    """Chunks of the document's current version (the searchable text)."""
    _, doc = readable_document(db, tenant_id, user_id, document_id)
    if doc.current_version_id is None:
        return [], 0
    query = select(KnowledgeChunkRecord).where(KnowledgeChunkRecord.version_id == doc.current_version_id,
                                               KnowledgeChunkRecord.parent_id.is_(None))
    total = db.execute(select(func.count()).select_from(query.subquery())).scalar_one()
    rows = db.scalars(query.order_by(KnowledgeChunkRecord.ordinal).offset(max(0, offset))
                      .limit(max(1, min(limit, 200)))).all()
    return list(rows), total


def chunk_view(chunk: KnowledgeChunkRecord) -> dict[str, Any]:
    return {'id': str(chunk.id), 'ordinal': chunk.ordinal, 'content': chunk.content, 'page': chunk.page,
            'section': list(chunk.section), 'char_start': chunk.char_start, 'char_end': chunk.char_end}


def cancel_graph_builds(db: Session, kb_id: UUID) -> None:
    """Stop unfinished graph builds of a base that is being deleted."""
    from nexus_platform.persistence.models import GraphBuildRecord
    for build in db.scalars(select(GraphBuildRecord).where(GraphBuildRecord.kb_id == kb_id,
                                                           GraphBuildRecord.state.in_(('pending', 'running')))):
        build.state, build.updated_at = 'cancelled', utc_now()


# Implemented here (capability catalog, decision 5).
capabilities.mark_available('kb_type', 'document')
capabilities.mark_available('kb_type', 'faq')
for _org_feature in ('tags', 'folders', 'pin', 'synonyms', 'structure_tools'):
    capabilities.mark_available('kb_feature', _org_feature)
for _chunk_feature in ('chunking_strategy', 'parent_child', 'chunking_debug'):
    capabilities.mark_available('kb_feature', _chunk_feature)
for _faq_feature in ('faq_entries', 'faq_import'):
    capabilities.mark_available('kb_feature', _faq_feature)
capabilities.mark_available('indexing', 'vector')
capabilities.mark_available('indexing', 'keyword')
capabilities.mark_available('parser_engine', 'builtin')
for _feature in ('documents', 'upload', 'chunking', 'embedding_model'):
    capabilities.mark_available('kb_feature', _feature)
capabilities.mark_available('indexing', 'graph')
for _mode in graph_config.MODES:
    capabilities.mark_available('graph_mode', _mode)
from .graph import neo4j as _neo4j  # noqa: E402,F401  (registers the neo4j graph store in the catalog)
capabilities.mark_available('graph_store', 'builtin')
for _feature in ('graph_settings', 'graph_browser'):
    capabilities.mark_available('kb_feature', _feature)
