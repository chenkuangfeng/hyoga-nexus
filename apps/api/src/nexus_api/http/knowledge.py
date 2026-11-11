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
from nexus_platform.configuration import knowledge_settings
from nexus_platform.errors import NotFound
from nexus_platform.identity.service import require_membership, resolve_user
from nexus_platform.knowledge import access, faq as faq_service, organize, search as knowledge_search, service, stores
from nexus_platform.persistence.models import (AuditRecord, KnowledgeBaseRecord, KnowledgeDocumentRecord,
                                               TenantRecord)
from nexus_platform.shared_spaces import kb_shares

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


@router.post('/bases/{kb_id}/profile/generate', status_code=202)
def generate_profile(tenant_id: UUID, kb_id: UUID, principal: Principal = Depends(get_principal),
                     db: Session = Depends(get_database_session)) -> dict[str, bool]:
    """Queue regeneration of the base's profile (a short description built from its documents)."""
    from nexus_platform.knowledge import enrich
    with db.begin():
        user = _user(db, principal, tenant_id)
        kb = access.maintainable_base(db, kb_id, tenant_id, user.id)
        enrich.request_profile(db, kb)
    return {'queued': True}


@router.post('/bases/{kb_id}/rebuild')
def rebuild_base(tenant_id: UUID, kb_id: UUID, principal: Principal = Depends(get_principal),
                 db: Session = Depends(get_database_session)) -> dict[str, int]:
    with db.begin():
        user = _user(db, principal, tenant_id)
        count = service.rebuild_base(db, tenant_id, user.id, kb_id)
    return {'documents': count}


# ---------------------------------------------------------------- graph

class GraphStoreInput(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    engine: str = Field(min_length=1, max_length=32)
    connection_config: dict[str, Any] = Field(default_factory=dict)


@router.get('/graph-stores')
def list_graph_stores(tenant_id: UUID, principal: Principal = Depends(get_principal),
                      db: Session = Depends(get_database_session)) -> dict[str, Any]:
    """``items``: stores a base can use (builtin + registered); ``engines``: catalog of graph store engines."""
    user = _user(db, principal, tenant_id)
    return {'items': stores.list_graph_stores(db, tenant_id, user.id),
            'engines': [{'engine': row['key'], 'name': row['label'], 'status': row['status'], 'stage': row['stage'],
                         'verified': row['verified'], 'builtin': row['key'] == 'builtin'}
                        for row in capabilities.snapshot() if row['group'] == 'graph_store']}


@router.post('/graph-stores', status_code=201)
def create_graph_store(tenant_id: UUID, body: GraphStoreInput, principal: Principal = Depends(get_principal),
                       db: Session = Depends(get_database_session)) -> dict[str, Any]:
    with db.begin():
        user = _user(db, principal, tenant_id)
        row = stores.create_graph_store(db, tenant_id, user.id, name=body.name, engine=body.engine,
                                        connection_config=body.connection_config)
    return stores.graph_store_view(row)


@router.delete('/graph-stores/{store_id}', status_code=204)
def delete_graph_store(tenant_id: UUID, store_id: UUID, principal: Principal = Depends(get_principal),
                       db: Session = Depends(get_database_session)) -> Response:
    with db.begin():
        user = _user(db, principal, tenant_id)
        stores.delete_graph_store(db, tenant_id, user.id, store_id)
    return Response(status_code=204)


@router.post('/graph-stores/test')
async def test_graph_store_draft(tenant_id: UUID, body: GraphStoreInput, principal: Principal = Depends(get_principal),
                                 db: Session = Depends(get_database_session)) -> dict[str, Any]:
    """Connection test of an unsaved graph store configuration (space admins)."""
    from nexus_platform.tenants.service import ADMIN_ROLES
    user = resolve_user(db, principal)
    require_membership(db, tenant_id, user.id, roles=ADMIN_ROLES)
    capabilities.require_available('graph_store', body.engine)
    return await _ping_graph_store(body.engine, body.connection_config)


@router.post('/graph-stores/{store_id}/test')
async def test_graph_store(tenant_id: UUID, store_id: str, principal: Principal = Depends(get_principal),
                           db: Session = Depends(get_database_session)) -> dict[str, Any]:
    user = _user(db, principal, tenant_id)
    if store_id == stores.BUILTIN:
        return {'ok': True, 'details': {'engine': 'builtin'}}
    from nexus_platform.persistence.models import GraphStoreRecord
    row = db.get(GraphStoreRecord, UUID(store_id))
    if row is None or row.tenant_id != tenant_id:
        raise NotFound('Graph store not found')
    return await _ping_graph_store(row.engine, stores.reveal_config(row.id, row.connection_config))


async def _ping_graph_store(engine: str, config: dict[str, Any]) -> dict[str, Any]:
    if engine != 'neo4j':
        return {'ok': False, 'code': 'unsupported', 'message': engine}
    from nexus_platform.knowledge.graph.neo4j import Neo4jError, Neo4jGraphStore
    try:
        store = Neo4jGraphStore(config)
        try:
            return {'ok': True, 'details': await store.ping()}
        finally:
            await store.close()
    except Neo4jError as exc:
        return {'ok': False, 'code': exc.code, 'message': str(exc)[:300]}


@router.get('/bases/{kb_id}/graph')
def get_graph_status(tenant_id: UUID, kb_id: UUID, principal: Principal = Depends(get_principal),
                     db: Session = Depends(get_database_session)) -> dict[str, Any]:
    from nexus_platform.knowledge.graph import views
    user = _user(db, principal, tenant_id)
    return views.status(db, access.readable_base(db, kb_id, tenant_id, user.id))


@router.post('/bases/{kb_id}/graph/rebuild', status_code=202)
def rebuild_graph(tenant_id: UUID, kb_id: UUID, principal: Principal = Depends(get_principal),
                  db: Session = Depends(get_database_session)) -> dict[str, Any]:
    from nexus_platform.knowledge.graph import views
    with db.begin():
        user = _user(db, principal, tenant_id)
        kb = access.maintainable_base(db, kb_id, tenant_id, user.id)
        build = views.request_rebuild(db, kb, user.id)
    return build


@router.get('/bases/{kb_id}/graph/overview')
async def graph_overview(tenant_id: UUID, kb_id: UUID, request: Request, names: str = Query('', max_length=500),
                         hops: int = Query(1, ge=1, le=3), limit: int = Query(60, ge=5, le=200),
                         principal: Principal = Depends(get_principal),
                         db: Session = Depends(get_database_session)) -> dict[str, Any]:
    """Nodes and edges for the graph browser: entities named in ``names`` (comma separated) with neighbours."""
    from nexus_platform.knowledge.graph import views
    user = _user(db, principal, tenant_id)
    factory = getattr(request.app.state, 'session_factory', None) or sessionmaker(
        bind=db.get_bind(), expire_on_commit=False, autoflush=False)
    wanted = [name.strip() for name in names.split(',') if name.strip()][:10]
    return await views.overview(factory, db, tenant_id, user.id, kb_id, names=wanted, hops=hops, limit=limit)


# ---------------------------------------------------------------- documents

@router.get('/bases/{kb_id}/documents')
def list_documents(tenant_id: UUID, kb_id: UUID, keyword: str = Query('', max_length=200),
                   tag_ids: str = Query('', max_length=2000), folder_path: str | None = Query(None, max_length=1024),
                   folder_recursive: bool = True, file_type: str = Query('', max_length=16),
                   offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200),
                   principal: Principal = Depends(get_principal),
                   db: Session = Depends(get_database_session)) -> dict[str, Any]:
    user = _user(db, principal, tenant_id)
    rows, total = service.list_documents(
        db, tenant_id, user.id, kb_id, keyword=keyword, offset=offset, limit=limit,
        tag_ids=[t for t in tag_ids.split(',') if t], folder=folder_path, recursive=folder_recursive, file_type=file_type)
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
        kb = access.maintainable_base(db, kb_id, tenant_id, user.id)
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


# ---------------------------------------------------------------- image gallery (K4.2)

@router.get('/bases/{kb_id}/images')
def list_images(tenant_id: UUID, kb_id: UUID, keyword: str = Query('', max_length=200),
                knowledge_ids: str = Query('', max_length=4000), offset: int = Query(0, ge=0),
                limit: int = Query(30, ge=1, le=100), principal: Principal = Depends(get_principal),
                db: Session = Depends(get_database_session)) -> dict[str, Any]:
    """Images of a base (image documents with their model-written captions). ``url`` is relative to this API."""
    from nexus_platform.knowledge import media
    user = _user(db, principal, tenant_id)
    kb = access.readable_base(db, kb_id, tenant_id, user.id)
    ids = []
    for value in knowledge_ids.split(','):
        try:
            ids.append(UUID(value))
        except ValueError:
            continue
    items, total = media.list_images(db, kb, keyword=keyword, document_ids=ids or None, offset=offset, limit=limit)
    prefix = f'/api/v1/tenants/{tenant_id}/knowledge/'
    return {'items': [{**item, 'url': prefix + item['url']} for item in items], 'total': total}


# ---------------------------------------------------------------- organization (K5)

class TagInput(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    color: str = Field('', max_length=32)
    sort_order: int = 0


class TagUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    color: str | None = Field(None, max_length=32)
    sort_order: int | None = None


class OrganizeInput(BaseModel):
    ids: list[UUID] = Field(min_length=1, max_length=500)
    tag_ids: list[UUID] | None = None
    folder_path: str | None = Field(None, max_length=1024)
    custom_metadata: dict[str, str] | None = None


class FolderRenameInput(BaseModel):
    source: str = Field(min_length=1, max_length=1024)
    target: str = Field(max_length=1024)


class TagBatchInput(BaseModel):
    updates: dict[UUID, list[UUID]] = Field(max_length=500)


@router.get('/bases/{kb_id}/tags')
def list_tags(tenant_id: UUID, kb_id: UUID, keyword: str = Query('', max_length=100),
              principal: Principal = Depends(get_principal), db: Session = Depends(get_database_session)):
    user = _user(db, principal, tenant_id)
    return {'items': organize.list_tags(db, tenant_id, user.id, kb_id, keyword)}


@router.post('/bases/{kb_id}/tags', status_code=201)
def create_tag(tenant_id: UUID, kb_id: UUID, body: TagInput, principal: Principal = Depends(get_principal),
               db: Session = Depends(get_database_session)):
    with db.begin():
        user = _user(db, principal, tenant_id)
        return organize.tag_view(organize.create_tag(db, tenant_id, user.id, kb_id, name=body.name, color=body.color,
                                                     sort_order=body.sort_order))


@router.put('/bases/{kb_id}/tags/{tag_id}')
def update_tag(tenant_id: UUID, kb_id: UUID, tag_id: UUID, body: TagUpdate, principal: Principal = Depends(get_principal),
               db: Session = Depends(get_database_session)):
    with db.begin():
        user = _user(db, principal, tenant_id)
        return organize.tag_view(organize.update_tag(db, tenant_id, user.id, kb_id, tag_id, body.model_dump(exclude_unset=True)))


@router.delete('/bases/{kb_id}/tags/{tag_id}')
def delete_tag(tenant_id: UUID, kb_id: UUID, tag_id: UUID, force: bool = False,
               principal: Principal = Depends(get_principal), db: Session = Depends(get_database_session)):
    with db.begin():
        user = _user(db, principal, tenant_id)
        return {'removed_from': organize.delete_tag(db, tenant_id, user.id, kb_id, tag_id, force=force)}


@router.patch('/bases/{kb_id}/documents')
def organize_documents(tenant_id: UUID, kb_id: UUID, body: OrganizeInput, principal: Principal = Depends(get_principal),
                       db: Session = Depends(get_database_session)):
    """Set tags, folder and/or custom metadata of documents; only the fields sent change."""
    changes = body.model_dump(exclude_unset=True, exclude={'ids'})
    with db.begin():
        user = _user(db, principal, tenant_id)
        return {'updated': organize.organize_documents(db, tenant_id, user.id, kb_id, body.ids, changes)}


@router.put('/document-tags')
def set_document_tags(tenant_id: UUID, body: TagBatchInput, principal: Principal = Depends(get_principal),
                      db: Session = Depends(get_database_session)):
    """WeKnora batch tagging: each document gets exactly the listed tags (write access to its base is checked)."""
    with db.begin():
        user = _user(db, principal, tenant_id)
        updates = {str(k): [str(t) for t in v] for k, v in body.updates.items()}
        return {'updated': organize.add_tags(db, tenant_id, user.id, updates)}


@router.get('/bases/{kb_id}/folders')
def get_folders(tenant_id: UUID, kb_id: UUID, principal: Principal = Depends(get_principal),
                db: Session = Depends(get_database_session)):
    user = _user(db, principal, tenant_id)
    return organize.folder_tree(db, tenant_id, user.id, kb_id)


@router.put('/bases/{kb_id}/folders')
def rename_folder(tenant_id: UUID, kb_id: UUID, body: FolderRenameInput, principal: Principal = Depends(get_principal),
                  db: Session = Depends(get_database_session)):
    with db.begin():
        user = _user(db, principal, tenant_id)
        return {'moved': organize.rename_folder(db, tenant_id, user.id, kb_id, body.source, body.target)}


@router.put('/bases/{kb_id}/pin')
def pin_base(tenant_id: UUID, kb_id: UUID, principal: Principal = Depends(get_principal),
             db: Session = Depends(get_database_session)):
    with db.begin():
        user = _user(db, principal, tenant_id)
        return {'is_pinned': organize.toggle_pin(db, tenant_id, user.id, kb_id)}


# ---------------------------------------------------------------- FAQ (K3)

class FaqEntryInput(BaseModel):
    standard_question: str = Field(max_length=2000)
    similar_questions: list[str] = Field(default_factory=list, max_length=200)
    negative_questions: list[str] = Field(default_factory=list, max_length=200)
    answers: list[str] = Field(default_factory=list, max_length=50)
    category: str = Field('', max_length=200)
    tag_id: UUID | None = None
    answer_strategy: Literal['all', 'first'] = 'all'
    is_enabled: bool = True
    is_recommended: bool = False


class FaqImportInput(BaseModel):
    entries: list[dict[str, Any]] = Field(max_length=faq_service.MAX_IMPORT)
    mode: Literal['append', 'replace'] = 'append'


class FaqFieldsInput(BaseModel):
    ids: list[UUID] = Field(min_length=1, max_length=2000)
    is_enabled: bool | None = None
    is_recommended: bool | None = None
    tag_id: UUID | None = None


class FaqIdsInput(BaseModel):
    ids: list[UUID] = Field(min_length=1, max_length=2000)


@router.get('/bases/{kb_id}/faq/entries')
def list_faq_entries(tenant_id: UUID, kb_id: UUID, keyword: str = Query('', max_length=200),
                     tag_ids: str = Query('', max_length=2000), is_enabled: bool | None = None, offset: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=200),
                     principal: Principal = Depends(get_principal), db: Session = Depends(get_database_session)):
    user = _user(db, principal, tenant_id)
    rows, total = faq_service.list_entries(db, tenant_id, user.id, kb_id, keyword=keyword, enabled=is_enabled,
                                           tag_ids=[t for t in tag_ids.split(',') if t], offset=offset, limit=limit)
    return {'items': [faq_service.view(row) for row in rows], 'total': total}


@router.post('/bases/{kb_id}/faq/entries', status_code=201)
def create_faq_entry(tenant_id: UUID, kb_id: UUID, body: FaqEntryInput, principal: Principal = Depends(get_principal),
                     db: Session = Depends(get_database_session)):
    with db.begin():
        user = _user(db, principal, tenant_id)
        row, notes = faq_service.create_entry(db, tenant_id, user.id, kb_id, body.model_dump())
        result = faq_service.view(row)
    return {**result, 'notes': notes}


@router.put('/bases/{kb_id}/faq/entries/{entry_id}')
def update_faq_entry(tenant_id: UUID, kb_id: UUID, entry_id: UUID, body: FaqEntryInput,
                     principal: Principal = Depends(get_principal), db: Session = Depends(get_database_session)):
    with db.begin():
        user = _user(db, principal, tenant_id)
        row, notes = faq_service.update_entry(db, tenant_id, user.id, kb_id, entry_id, body.model_dump(exclude_unset=True))
        result = faq_service.view(row)
    return {**result, 'notes': notes}


@router.patch('/bases/{kb_id}/faq/entries')
def update_faq_fields(tenant_id: UUID, kb_id: UUID, body: FaqFieldsInput, principal: Principal = Depends(get_principal),
                      db: Session = Depends(get_database_session)):
    changes = body.model_dump(exclude_unset=True, exclude={'ids'})
    with db.begin():
        user = _user(db, principal, tenant_id)
        return {'updated': faq_service.batch_fields(db, tenant_id, user.id, kb_id, body.ids, changes)}


@router.post('/bases/{kb_id}/faq/entries/delete')
def delete_faq_entries(tenant_id: UUID, kb_id: UUID, body: FaqIdsInput, principal: Principal = Depends(get_principal),
                       db: Session = Depends(get_database_session)):
    with db.begin():
        user = _user(db, principal, tenant_id)
        return {'deleted': faq_service.delete_entries(db, tenant_id, user.id, kb_id, body.ids)}


@router.post('/bases/{kb_id}/faq/import')
def import_faq(tenant_id: UUID, kb_id: UUID, body: FaqImportInput, principal: Principal = Depends(get_principal),
               db: Session = Depends(get_database_session)):
    with db.begin():
        user = _user(db, principal, tenant_id)
        return faq_service.import_entries(db, tenant_id, user.id, kb_id, body.entries, body.mode)


@router.post('/bases/{kb_id}/faq/import-file')
async def import_faq_file(tenant_id: UUID, kb_id: UUID, file: UploadFile = File(...), mode: str = Form('append'),
                          principal: Principal = Depends(get_principal), db: Session = Depends(get_database_session)):
    """Import a WeKnora-format CSV (columns 分类, 问题, 相似问题, 反例问题, 机器人回答, 是否全部回复, 是否停用)."""
    from nexus_knowledge import faq as faq_rules
    data = await file.read(knowledge_settings().max_upload_mb * 1024 * 1024 + 1)
    rows = faq_rules.parse_csv(data)
    with db.begin():
        user = _user(db, principal, tenant_id)
        return faq_service.import_entries(db, tenant_id, user.id, kb_id, rows, mode)


@router.get('/bases/{kb_id}/faq/export')
def export_faq(tenant_id: UUID, kb_id: UUID, format: Literal['csv', 'json'] = 'csv',
               principal: Principal = Depends(get_principal), db: Session = Depends(get_database_session)):
    from nexus_knowledge import faq as faq_rules
    user = _user(db, principal, tenant_id)
    rows = faq_service.export_entries(db, tenant_id, user.id, kb_id)
    if format == 'json':
        import json as _json
        return Response(_json.dumps(rows, ensure_ascii=False, indent=2).encode(), media_type='application/json',
                        headers={'Content-Disposition': 'attachment; filename="faq.json"'})
    return Response(faq_rules.to_csv(rows), media_type='text/csv; charset=utf-8',
                    headers={'Content-Disposition': 'attachment; filename="faq.csv"'})


@router.post('/bases/{kb_id}/faq/retry')
def retry_faq_index(tenant_id: UUID, kb_id: UUID, principal: Principal = Depends(get_principal),
                    db: Session = Depends(get_database_session)):
    with db.begin():
        user = _user(db, principal, tenant_id)
        return {'retried': faq_service.retry_failed(db, tenant_id, user.id, kb_id)}


class FaqSearchInput(BaseModel):
    query_text: str = Field(min_length=1, max_length=2000)
    match_count: int = Field(10, ge=1, le=50)


@router.post('/bases/{kb_id}/faq/search')
async def search_faq(tenant_id: UUID, kb_id: UUID, body: FaqSearchInput, request: Request,
                     principal: Principal = Depends(get_principal), db: Session = Depends(get_database_session)):
    """Search one FAQ base; hits carry the entry, the score and the channels that matched."""
    user = _user(db, principal, tenant_id)
    access.readable_base(db, kb_id, tenant_id, user.id)
    factory = getattr(request.app.state, 'session_factory', None) or sessionmaker(
        bind=db.get_bind(), expire_on_commit=False, autoflush=False)
    result = await knowledge_search.search(factory, db, tenant_id, user.id, body.query_text, limit=body.match_count,
                                           requested=[kb_id])
    db.commit()
    return {'items': [knowledge_search.hit_view(hit) for hit in result.hits], 'degraded': result.degraded}


# ---------------------------------------------------------------- chunking and parser engines (K4)

class ChunkingPreviewInput(BaseModel):
    text: str = Field(min_length=1, max_length=64 * 1024)
    chunking_config: dict[str, Any] = Field(default_factory=dict)


@router.post('/chunk-preview')
def preview_chunking(tenant_id: UUID, body: ChunkingPreviewInput, principal: Principal = Depends(get_principal),
                     db: Session = Depends(get_database_session)) -> dict[str, Any]:
    """Run the chunker over sample text without storing anything (the editor's chunking debug panel)."""
    from nexus_knowledge.ingest import chunk as chunking
    from nexus_knowledge.ingest.parse import parse_markdown
    _user(db, principal, tenant_id)
    raw = body.chunking_config
    config = chunking.ChunkConfig.from_settings(
        int(raw.get('chunk_size') or chunking.DEFAULT_SIZE), int(raw.get('chunk_overlap') or 0),
        {'strategy': raw.get('strategy') or 'auto', 'separators': raw.get('separators') or [],
         'enable_parent_child': raw.get('enable_parent_child'), 'parent_chunk_size': raw.get('parent_chunk_size'),
         'child_chunk_size': raw.get('child_chunk_size')})
    return {'success': True, 'data': chunking.preview(parse_markdown(body.text), config)}


@router.get('/parser-engines')
def list_parser_engines(tenant_id: UUID, principal: Principal = Depends(get_principal),
                        db: Session = Depends(get_database_session)) -> dict[str, Any]:
    """Parser engines with file types and state (configured / planned); settings are those of this space."""
    from nexus_knowledge.ingest.parse import SUPPORTED_SUFFIXES
    from nexus_platform.knowledge import media, parsers
    user = _user(db, principal, tenant_id)
    builtin_types = sorted(s.lstrip('.') for s in SUPPORTED_SUFFIXES | media.media_suffixes())
    return {'data': parsers.engine_list(parsers.load_config(db, tenant_id), builtin_types), 'connected': True}


@router.get('/parser-engine-config')
def get_parser_engine_config(tenant_id: UUID, principal: Principal = Depends(get_principal),
                             db: Session = Depends(get_database_session)) -> dict[str, Any]:
    from nexus_platform.knowledge import parsers
    user = _user(db, principal, tenant_id)
    return {'data': parsers.masked_config(db, tenant_id, user.id)}


@router.put('/parser-engine-config')
def put_parser_engine_config(tenant_id: UUID, body: dict[str, Any], principal: Principal = Depends(get_principal),
                             db: Session = Depends(get_database_session)) -> dict[str, Any]:
    """Replace the external engine settings of the space (owners and admins). Secrets are write-only."""
    from nexus_platform.knowledge import parsers
    with db.begin():
        user = _user(db, principal, tenant_id)
        return {'data': parsers.save_config(db, tenant_id, user.id, body)}


# ---------------------------------------------------------------- retrieval test

class SearchInput(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    kb_ids: list[UUID] | None = None
    limit: int = Field(8, ge=1, le=knowledge_search.MAX_LIMIT)
    tag_ids: list[UUID] = Field(default_factory=list, max_length=50)
    folder_path: str | None = Field(None, max_length=1024)
    metadata: dict[str, str] = Field(default_factory=dict, max_length=20)
    #: False skips reranking even when the base enables it (retrieval test).
    rerank: bool = True
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
                                           keyword_weight=body.keyword_weight, rerank=body.rerank,
                                           doc_filter=organize.DocumentFilter(
                                               tuple(str(t) for t in body.tag_ids),
                                               organize.clean_folder(body.folder_path) if body.folder_path is not None else None,
                                               True, body.metadata))
    db.commit()  # degradation audits
    return {'items': [knowledge_search.hit_view(hit) for hit in result.hits], 'degraded': result.degraded,
            'searched': result.searched, 'ignored': result.ignored, 'rerank': result.rerank}


# ---------------------------------------------------------------- sharing and activity

class ShareInput(BaseModel):
    shared_space_id: UUID
    level: Literal['viewer', 'editor', 'admin'] = 'viewer'


@router.get('/bases/{kb_id}/shares')
def list_shares(tenant_id: UUID, kb_id: UUID, principal: Principal = Depends(get_principal),
                db: Session = Depends(get_database_session)) -> dict[str, Any]:
    """Shared spaces the base is shared into (owning space's owner or admin)."""
    return {'items': kb_shares.list_base_shares(db, principal, tenant_id, kb_id)}


@router.post('/bases/{kb_id}/shares', status_code=201)
def share_base(tenant_id: UUID, kb_id: UUID, body: ShareInput, principal: Principal = Depends(get_principal),
               db: Session = Depends(get_database_session)) -> dict[str, Any]:
    """Share a base of this space into a shared space; sharing again changes the level."""
    return kb_shares.share_base(db, principal, tenant_id, kb_id, body.shared_space_id, body.level)


@router.delete('/bases/{kb_id}/shares/{shared_space_id}', status_code=204)
def unshare_base(tenant_id: UUID, kb_id: UUID, shared_space_id: UUID, principal: Principal = Depends(get_principal),
                 db: Session = Depends(get_database_session)) -> Response:
    kb_shares.unshare_base(db, principal, tenant_id, kb_id, shared_space_id)
    return Response(status_code=204)


@router.get('/shared-bases')
def list_shared_bases(tenant_id: UUID, principal: Principal = Depends(get_principal),
                      db: Session = Depends(get_database_session)) -> dict[str, Any]:
    """Bases of other spaces readable here through a shared space, with the effective level."""
    user = _user(db, principal, tenant_id)
    levels = kb_shares.shared_levels(db, tenant_id, user.id)
    items = []
    for kb in access.readable_bases(db, tenant_id, user.id, list(levels) or None) if levels else []:
        if kb.tenant_id == tenant_id or kb.id not in levels:
            continue
        owner = db.get(TenantRecord, kb.tenant_id)
        items.append({**service.base_view(db, kb, tenant_id, user.id), 'level': levels[kb.id],
                      'owner_tenant_id': str(kb.tenant_id), 'owner_tenant_name': owner.name if owner else ''})
    return {'items': items}


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
