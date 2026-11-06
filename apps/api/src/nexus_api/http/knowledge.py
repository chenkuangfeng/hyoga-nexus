"""Knowledge base HTTP API (openspec 2026-11-06-knowledge-base K0–K1).

All routes live under ``/api/v1/tenants/{tenant_id}/knowledge`` and act from the caller's current space
``tenant_id``: bases of the space plus bases shared into it are readable; only bases of the space can be
changed. Every search goes through the same Pre-Filter as the agent tools (``nexus_platform.knowledge.search``).

Choosing a feature the capability catalog marks ``planned`` answers 422 ``capability_planned``.
"""
from __future__ import annotations

from typing import Any, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, sessionmaker

from nexus_api.dependencies.platform import get_database_session, get_principal
from nexus_core.platform import Principal
from nexus_knowledge import capabilities
from nexus_knowledge import index as _engines  # noqa: F401  (registers the vector engines in the catalog)
from nexus_platform.authz.resources import grant_resource, revoke_resource_grant
from nexus_platform.configuration import knowledge_settings
from nexus_platform.errors import NotFound
from nexus_platform.identity.service import require_membership, resolve_user
from nexus_platform.knowledge import access, search as knowledge_search, service, stores
from nexus_platform.persistence.models import (AuditRecord, KnowledgeBaseRecord, KnowledgeDocumentRecord,
                                               ResourceGrantRecord, TenantRecord)

router = APIRouter(prefix='/api/v1/tenants/{tenant_id}/knowledge', tags=['Knowledge'])

for _feature in ('retrieval_test', 'share', 'activity'):
    capabilities.mark_available('kb_feature', _feature)


def _user(db: Session, principal: Principal, tenant_id: UUID):
    user = resolve_user(db, principal)
    require_membership(db, tenant_id, user.id)
    return user


@router.get('/capabilities')
def list_capabilities(tenant_id: UUID, principal: Principal = Depends(get_principal),
                      db: Session = Depends(get_database_session)) -> dict[str, object]:
    """Every knowledge feature with ``status`` (available | planned), ``stage`` and ``verified``."""
    _user(db, principal, tenant_id)
    return {'groups': list(capabilities.GROUPS), 'items': capabilities.snapshot()}


# ---------------------------------------------------------------- knowledge bases

class ChunkingInput(BaseModel):
    chunk_size: int = Field(800, ge=100, le=10000)
    chunk_overlap: int = Field(120, ge=0, le=5000)


class BaseInput(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str = Field('', max_length=2000)
    type: Literal['document', 'faq', 'wiki'] = 'document'
    indexing_strategy: dict[str, bool] = Field(default_factory=lambda: dict(service.DEFAULT_INDEXING))
    vector_store_id: str | None = None
    storage_backend_id: str | None = None
    embedding_model_id: UUID | None = None
    chunking_config: ChunkingInput = Field(default_factory=ChunkingInput)
    #: WeKnora configuration blocks of later stages, kept as submitted (FAQ, Wiki, graph, parser rules...).
    settings: dict[str, Any] = Field(default_factory=dict)


class BaseUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=160)
    description: str | None = Field(None, max_length=2000)
    indexing_strategy: dict[str, bool] | None = None
    embedding_model_id: UUID | None = None
    chunking_config: ChunkingInput | None = None
    settings: dict[str, Any] | None = None


@router.get('/bases')
def list_bases(tenant_id: UUID, principal: Principal = Depends(get_principal),
               db: Session = Depends(get_database_session)) -> dict[str, Any]:
    user = _user(db, principal, tenant_id)
    rows = service.list_bases(db, tenant_id, user.id)
    return {'items': [service.base_view(db, kb, tenant_id, user.id) for kb in rows]}


@router.post('/bases', status_code=201)
def create_base(tenant_id: UUID, body: BaseInput, principal: Principal = Depends(get_principal),
                db: Session = Depends(get_database_session)) -> dict[str, Any]:
    with db.begin():
        user = _user(db, principal, tenant_id)
        kb = service.create_base(
            db, tenant_id, user.id, name=body.name, description=body.description, kb_type=body.type,
            indexing=body.indexing_strategy, vector_store_id=body.vector_store_id,
            storage_backend_id=body.storage_backend_id, embedding_model_id=body.embedding_model_id,
            chunk_size=body.chunking_config.chunk_size, chunk_overlap=body.chunking_config.chunk_overlap,
            settings=body.settings)
    return service.base_view(db, kb, tenant_id, user.id)


@router.get('/bases/{kb_id}')
def get_base(tenant_id: UUID, kb_id: UUID, principal: Principal = Depends(get_principal),
             db: Session = Depends(get_database_session)) -> dict[str, Any]:
    user = _user(db, principal, tenant_id)
    return service.base_view(db, access.readable_base(db, kb_id, tenant_id, user.id), tenant_id, user.id)


@router.patch('/bases/{kb_id}')
def update_base(tenant_id: UUID, kb_id: UUID, body: BaseUpdate, principal: Principal = Depends(get_principal),
                db: Session = Depends(get_database_session)) -> dict[str, Any]:
    changes = body.model_dump(exclude_unset=True)
    if 'chunking_config' in changes and changes['chunking_config'] is not None:
        changes['chunking_config'] = dict(changes['chunking_config'])
    with db.begin():
        user = _user(db, principal, tenant_id)
        kb = service.update_base(db, tenant_id, user.id, kb_id, changes)
    return service.base_view(db, kb, tenant_id, user.id)


@router.delete('/bases/{kb_id}', status_code=204)
def delete_base(tenant_id: UUID, kb_id: UUID, principal: Principal = Depends(get_principal),
                db: Session = Depends(get_database_session)) -> Response:
    with db.begin():
        user = _user(db, principal, tenant_id)
        service.delete_base(db, tenant_id, user.id, kb_id)
    return Response(status_code=204)


@router.post('/bases/{kb_id}/rebuild')
def rebuild_base(tenant_id: UUID, kb_id: UUID, principal: Principal = Depends(get_principal),
                 db: Session = Depends(get_database_session)) -> dict[str, int]:
    with db.begin():
        user = _user(db, principal, tenant_id)
        count = service.rebuild_base(db, tenant_id, user.id, kb_id)
    return {'documents': count}


# ---------------------------------------------------------------- documents

@router.get('/bases/{kb_id}/documents')
def list_documents(tenant_id: UUID, kb_id: UUID, keyword: str = Query('', max_length=200),
                   offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200),
                   principal: Principal = Depends(get_principal),
                   db: Session = Depends(get_database_session)) -> dict[str, Any]:
    user = _user(db, principal, tenant_id)
    rows, total = service.list_documents(db, tenant_id, user.id, kb_id, keyword=keyword, offset=offset, limit=limit)
    return {'items': [service.document_view(db, doc) for doc in rows], 'total': total}


@router.post('/bases/{kb_id}/documents', status_code=201)
async def upload_document(tenant_id: UUID, kb_id: UUID, file: UploadFile = File(...),
                          filename: str | None = Form(None), principal: Principal = Depends(get_principal),
                          db: Session = Depends(get_database_session)) -> dict[str, Any]:
    """Multipart upload (field ``file``). Same bytes already in the base: ``deduplicated: true``, no new version."""
    limit = knowledge_settings().max_upload_mb * 1024 * 1024
    data = await file.read(limit + 1)
    name = filename or file.filename or ''
    user = _user(db, principal, tenant_id)
    kb, digest, duplicate = service.prepare_upload(db, tenant_id, user.id, kb_id, name, data, limit)
    if duplicate is not None:
        return {'document': service.document_view(db, duplicate), 'deduplicated': True}
    existing = db.scalar(select(KnowledgeDocumentRecord.id).where(
        KnowledgeDocumentRecord.kb_id == kb.id, KnowledgeDocumentRecord.status == 'active',
        KnowledgeDocumentRecord.filename == name.strip().replace('\\', '/').rsplit('/', 1)[-1]))
    document_id, version_id = existing or uuid4(), uuid4()
    blob = stores.blob_store_for(db, kb)
    key = service.blob_key(kb, document_id, version_id)
    db.rollback()  # end the read transaction before the (possibly slow) file write; do not touch kb after this
    await blob.put(key, data)
    with db.begin():
        kb = access.writable_base(db, kb_id, tenant_id, user.id)
        doc, _ = service.add_version(db, kb, user.id, name, digest, len(data), document_id, version_id)
    return {'document': service.document_view(db, doc), 'deduplicated': False}


@router.get('/documents/{document_id}')
def get_document(tenant_id: UUID, document_id: UUID, principal: Principal = Depends(get_principal),
                 db: Session = Depends(get_database_session)) -> dict[str, Any]:
    user = _user(db, principal, tenant_id)
    _, doc = service.readable_document(db, tenant_id, user.id, document_id)
    return service.document_view(db, doc)


@router.get('/documents/{document_id}/versions')
def list_versions(tenant_id: UUID, document_id: UUID, principal: Principal = Depends(get_principal),
                  db: Session = Depends(get_database_session)) -> dict[str, Any]:
    user = _user(db, principal, tenant_id)
    return {'items': [service.version_view(v) for v in service.list_versions(db, tenant_id, user.id, document_id)]}


@router.get('/documents/{document_id}/chunks')
def list_chunks(tenant_id: UUID, document_id: UUID, offset: int = Query(0, ge=0),
                limit: int = Query(50, ge=1, le=200), principal: Principal = Depends(get_principal),
                db: Session = Depends(get_database_session)) -> dict[str, Any]:
    user = _user(db, principal, tenant_id)
    rows, total = service.chunks_of(db, tenant_id, user.id, document_id, offset=offset, limit=limit)
    return {'items': [service.chunk_view(chunk) for chunk in rows], 'total': total}


@router.get('/documents/{document_id}/download')
async def download_document(tenant_id: UUID, document_id: UUID, principal: Principal = Depends(get_principal),
                            db: Session = Depends(get_database_session)) -> Response:
    user = _user(db, principal, tenant_id)
    kb, doc = service.readable_document(db, tenant_id, user.id, document_id)
    from nexus_platform.persistence.models import KnowledgeDocumentVersionRecord
    version = db.get(KnowledgeDocumentVersionRecord, doc.current_version_id or doc.latest_version_id)
    if version is None:
        raise NotFound('Document has no stored file')
    data = await stores.blob_store_for(db, kb).get(version.blob_key)
    from urllib.parse import quote
    # ASCII fallback for old clients; the UTF-8 name goes in filename* (RFC 6266).
    quoted = ''.join(ch if 32 <= ord(ch) < 127 and ch not in '"\\' else '_' for ch in doc.filename)
    return Response(data, media_type=version.mime or 'application/octet-stream', headers={
        'Content-Disposition': f'attachment; filename="{quoted}"; filename*=UTF-8\'\'{quote(doc.filename)}'})


@router.post('/documents/{document_id}/retry')
def retry_document(tenant_id: UUID, document_id: UUID, principal: Principal = Depends(get_principal),
                   db: Session = Depends(get_database_session)) -> dict[str, Any]:
    with db.begin():
        user = _user(db, principal, tenant_id)
        version = service.retry_document(db, tenant_id, user.id, document_id)
    return service.version_view(version)


@router.delete('/documents/{document_id}', status_code=204)
def delete_document(tenant_id: UUID, document_id: UUID, principal: Principal = Depends(get_principal),
                    db: Session = Depends(get_database_session)) -> Response:
    with db.begin():
        user = _user(db, principal, tenant_id)
        service.delete_document(db, tenant_id, user.id, document_id)
    return Response(status_code=204)


# ---------------------------------------------------------------- retrieval test

class SearchInput(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    kb_ids: list[UUID] | None = None
    limit: int = Field(8, ge=1, le=knowledge_search.MAX_LIMIT)
    vector_weight: float = Field(1.0, ge=0, le=10)
    keyword_weight: float = Field(1.0, ge=0, le=10)


@router.post('/search')
async def search(tenant_id: UUID, body: SearchInput, request: Request, principal: Principal = Depends(get_principal),
                 db: Session = Depends(get_database_session)) -> dict[str, Any]:
    """Retrieval test: the same Pre-Filter and fusion as ``search_knowledge``, with per-channel diagnostics."""
    user = _user(db, principal, tenant_id)
    factory = getattr(request.app.state, 'session_factory', None) or sessionmaker(
        bind=db.get_bind(), expire_on_commit=False, autoflush=False)
    result = await knowledge_search.search(factory, db, tenant_id, user.id, body.query, limit=body.limit,
                                           requested=body.kb_ids, vector_weight=body.vector_weight,
                                           keyword_weight=body.keyword_weight)
    db.commit()  # degradation audits
    return {'items': [knowledge_search.hit_view(hit) for hit in result.hits], 'degraded': result.degraded,
            'searched': result.searched, 'ignored': result.ignored}


# ---------------------------------------------------------------- sharing and activity

class ShareInput(BaseModel):
    target_tenant_id: UUID
    permissions: list[Literal['read', 'use']] = Field(default_factory=lambda: ['read', 'use'])


@router.get('/bases/{kb_id}/shares')
def list_shares(tenant_id: UUID, kb_id: UUID, principal: Principal = Depends(get_principal),
                db: Session = Depends(get_database_session)) -> dict[str, Any]:
    user = _user(db, principal, tenant_id)
    kb = access.readable_base(db, kb_id, tenant_id, user.id)
    rows = db.execute(select(ResourceGrantRecord, TenantRecord).join(
        TenantRecord, TenantRecord.id == ResourceGrantRecord.target_tenant_id).where(
        ResourceGrantRecord.source_tenant_id == kb.tenant_id, ResourceGrantRecord.kind == access.KIND,
        ResourceGrantRecord.resource_id == str(kb.id), ResourceGrantRecord.revoked_at.is_(None))).all()
    return {'items': [{'id': str(grant.id), 'target_tenant_id': str(tenant.id), 'target_tenant_name': tenant.name,
                       'permissions': grant.permissions, 'created_at': grant.created_at.isoformat()}
                      for grant, tenant in rows]}


@router.post('/bases/{kb_id}/shares', status_code=201)
def share_base(tenant_id: UUID, kb_id: UUID, body: ShareInput, principal: Principal = Depends(get_principal),
               db: Session = Depends(get_database_session)) -> dict[str, Any]:
    """Share a base of this space into another space (read-only there). Space owners and admins only."""
    user = _user(db, principal, tenant_id)
    kb = access.readable_base(db, kb_id, tenant_id, user.id)
    if kb.tenant_id != tenant_id:
        raise NotFound('Knowledge base not found')
    db.rollback()
    grant = grant_resource(db, principal, source_tenant_id=tenant_id, target_tenant_id=body.target_tenant_id,
                           kind=access.KIND, resource_id=str(kb_id), permissions=list(body.permissions))
    return {'id': str(grant.id), 'target_tenant_id': str(grant.target_tenant_id), 'permissions': grant.permissions}


@router.delete('/shares/{grant_id}', status_code=204)
def revoke_share(tenant_id: UUID, grant_id: UUID, principal: Principal = Depends(get_principal),
                 db: Session = Depends(get_database_session)) -> Response:
    _user(db, principal, tenant_id)
    grant = db.get(ResourceGrantRecord, grant_id)
    if grant is None or grant.kind != access.KIND or grant.source_tenant_id != tenant_id:
        raise NotFound('Share not found')
    db.rollback()
    revoke_resource_grant(db, principal, grant_id)
    return Response(status_code=204)


@router.get('/bases/{kb_id}/activity')
def list_activity(tenant_id: UUID, kb_id: UUID, limit: int = Query(50, ge=1, le=200),
                  principal: Principal = Depends(get_principal),
                  db: Session = Depends(get_database_session)) -> dict[str, Any]:
    """Audit records of the base and its documents, newest first (WeKnora activity log)."""
    user = _user(db, principal, tenant_id)
    kb = access.readable_base(db, kb_id, tenant_id, user.id)
    doc_ids = [str(i) for i in db.scalars(select(KnowledgeDocumentRecord.id).where(
        KnowledgeDocumentRecord.kb_id == kb.id))]
    rows = db.scalars(select(AuditRecord).where(AuditRecord.tenant_id == kb.tenant_id, or_(
        (AuditRecord.target_type == access.KIND) & (AuditRecord.target_id == str(kb.id)),
        (AuditRecord.target_type == 'knowledge_document') & AuditRecord.target_id.in_(doc_ids or ['-'])))
        .order_by(AuditRecord.created_at.desc()).limit(limit)).all()
    return {'items': [{'id': str(r.id), 'action': r.action, 'target_type': r.target_type, 'target_id': r.target_id,
                       'actor_user_id': str(r.actor_user_id), 'result': r.result, 'metadata': r.metadata_json,
                       'created_at': r.created_at.isoformat()} for r in rows]}


# ---------------------------------------------------------------- vector stores and storage backends

class VectorStoreInput(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    engine: str = Field(min_length=1, max_length=32)
    connection_config: dict[str, Any] = Field(default_factory=dict)
    index_config: dict[str, Any] = Field(default_factory=dict)


class VectorStoreUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    connection_config: dict[str, Any] = Field(default_factory=dict)
    index_config: dict[str, Any] = Field(default_factory=dict)


class StorageBackendInput(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    provider: str = Field(min_length=1, max_length=32)
    config: dict[str, Any] = Field(default_factory=dict)


@router.get('/vector-store-types')
def list_vector_store_types(tenant_id: UUID, principal: Principal = Depends(get_principal),
                            db: Session = Depends(get_database_session)) -> dict[str, Any]:
    """Every cataloged vector engine with its form fields, ``status`` and ``verified`` (planned: no fields)."""
    from nexus_knowledge.index.schemas import CONNECTION_FIELDS, INDEX_FIELDS
    _user(db, principal, tenant_id)
    items = []
    for row in capabilities.snapshot():
        if row['group'] != 'vector_engine':
            continue
        available = row['status'] == 'available'
        items.append({'type': row['key'], 'display_name': row['label'], 'status': row['status'],
                      'stage': row['stage'], 'verified': row['verified'],
                      'connection_fields': CONNECTION_FIELDS.get(row['key'], []) if available else [],
                      'index_fields': INDEX_FIELDS.get(row['key'], []) if available else []})
    return {'items': items}


@router.get('/vector-stores')
def list_vector_stores(tenant_id: UUID, principal: Principal = Depends(get_principal),
                       db: Session = Depends(get_database_session)) -> dict[str, Any]:
    user = _user(db, principal, tenant_id)
    return {'items': stores.list_vector_stores(db, tenant_id, user.id)}


@router.post('/vector-stores', status_code=201)
def create_vector_store(tenant_id: UUID, body: VectorStoreInput, principal: Principal = Depends(get_principal),
                        db: Session = Depends(get_database_session)) -> dict[str, Any]:
    with db.begin():
        user = _user(db, principal, tenant_id)
        row = stores.create_vector_store(db, tenant_id, user.id, name=body.name, engine=body.engine,
                                         connection_config=body.connection_config, index_config=body.index_config)
    return stores.vector_store_view(row)


@router.put('/vector-stores/{store_id}')
def update_vector_store(tenant_id: UUID, store_id: UUID, body: VectorStoreUpdate,
                        principal: Principal = Depends(get_principal),
                        db: Session = Depends(get_database_session)) -> dict[str, Any]:
    with db.begin():
        user = _user(db, principal, tenant_id)
        row = stores.update_vector_store(db, tenant_id, user.id, store_id, name=body.name,
                                         connection_config=body.connection_config, index_config=body.index_config)
    return stores.vector_store_view(row)


@router.delete('/vector-stores/{store_id}', status_code=204)
def delete_vector_store(tenant_id: UUID, store_id: UUID, principal: Principal = Depends(get_principal),
                        db: Session = Depends(get_database_session)) -> Response:
    with db.begin():
        user = _user(db, principal, tenant_id)
        stores.delete_vector_store(db, tenant_id, user.id, store_id)
    return Response(status_code=204)


@router.post('/vector-stores/{store_id}/test')
async def test_vector_store(tenant_id: UUID, store_id: str, principal: Principal = Depends(get_principal),
                            db: Session = Depends(get_database_session)) -> dict[str, Any]:
    """Connection test of a registered store (``builtin`` for the builtin SQLite store)."""
    user = _user(db, principal, tenant_id)
    row = stores.vector_store_of_tenant(db, tenant_id, store_id)
    index = stores.builtin_vector_index() if row is None else _engines.open_index(
        row.engine, stores.reveal_config(row.id, row.connection_config), row.index_config)
    return await _ping(index)


@router.post('/vector-stores/test')
async def test_vector_store_draft(tenant_id: UUID, body: VectorStoreInput, principal: Principal = Depends(get_principal),
                                  db: Session = Depends(get_database_session)) -> dict[str, Any]:
    """Connection test of an unsaved configuration (space admins); nothing is stored."""
    from nexus_platform.tenants.service import ADMIN_ROLES
    user = resolve_user(db, principal)
    require_membership(db, tenant_id, user.id, roles=ADMIN_ROLES)
    capabilities.require_available('vector_engine', body.engine)
    return await _ping(_engines.open_index(body.engine, body.connection_config, body.index_config))


async def _ping(index) -> dict[str, Any]:
    try:
        return {'ok': True, 'details': await index.ping()}
    except _engines.VectorStoreError as exc:
        return {'ok': False, 'code': exc.code, 'message': str(exc)[:300]}
    finally:
        await index.close()


@router.get('/storage-backends')
def list_storage_backends(tenant_id: UUID, principal: Principal = Depends(get_principal),
                          db: Session = Depends(get_database_session)) -> dict[str, Any]:
    user = _user(db, principal, tenant_id)
    return {'items': stores.list_storage_backends(db, tenant_id, user.id)}


@router.post('/storage-backends', status_code=201)
def create_storage_backend(tenant_id: UUID, body: StorageBackendInput, principal: Principal = Depends(get_principal),
                           db: Session = Depends(get_database_session)) -> dict[str, Any]:
    with db.begin():
        user = _user(db, principal, tenant_id)
        row = stores.create_storage_backend(db, tenant_id, user.id, name=body.name, provider=body.provider,
                                            config=body.config)
    return stores.storage_backend_view(row)


@router.delete('/storage-backends/{backend_id}', status_code=204)
def delete_storage_backend(tenant_id: UUID, backend_id: UUID, principal: Principal = Depends(get_principal),
                           db: Session = Depends(get_database_session)) -> Response:
    with db.begin():
        user = _user(db, principal, tenant_id)
        stores.delete_storage_backend(db, tenant_id, user.id, backend_id)
    return Response(status_code=204)


@router.post('/storage-backends/{backend_id}/test')
async def test_storage_backend(tenant_id: UUID, backend_id: str, principal: Principal = Depends(get_principal),
                               db: Session = Depends(get_database_session)) -> dict[str, Any]:
    user = _user(db, principal, tenant_id)
    row = stores.storage_backend_of_tenant(db, tenant_id, backend_id)
    from nexus_knowledge.providers import BlobStoreError, open_blob_store
    blob = stores.builtin_blob_store() if row is None else open_blob_store(
        row.provider, stores.reveal_config(row.id, row.config))
    try:
        return {'ok': True, 'details': await blob.ping()}
    except (BlobStoreError, OSError) as exc:
        return {'ok': False, 'code': getattr(exc, 'code', 'io_error'), 'message': str(exc)[:300]}
