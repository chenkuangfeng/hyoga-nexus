"""Graph builds (openspec 2026-11-06-knowledge-base K2.2–K2.5).

A build row is both the job and its result. The worker claims due builds and runs the stages:

1. ``extract``: for every chunk of the current document versions, the per-chunk extraction is read from the
   cache or produced by the model (creator's key) and cached. A rebuild after a document change therefore calls
   the model only for new text.
2. ``merge``: conservative merge into one graph (`nexus_knowledge.graph.merge`).
3. ``communities`` + ``reports`` (``graphrag_general``): Louvain communities, one report per community.
4. ``write``: the graph store persists the build.
5. ``index``: entities, relations and community reports are added to the knowledge base's vector index (a
   second collection, ``g`` + base id) so search finds them by keywords and, when the base has an embedding
   model, by meaning.
6. The build becomes ``ready`` and older builds are superseded and deleted. Until then the previous ready
   build stays searchable; a failed build never changes what is visible.

Bounds: at most :data:`MAX_CHUNKS` chunks per build (reported in ``progress.truncated``), at most
:data:`MAX_REPORTS` community reports. Errors retry with backoff, then the build fails with the reason.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from nexus_core.platform import new_id, utc_now
from nexus_knowledge import capabilities
from nexus_knowledge.graph import community as community_rules
from nexus_knowledge.graph import extract, merge
from nexus_knowledge.index import IndexRow
from nexus_knowledge.text import tokenize
from nexus_platform.errors import NotFound, PlatformError
from nexus_platform.knowledge import embedding, stores
from nexus_platform.persistence.models import (GraphBuildRecord, GraphStoreRecord, GraphExtractionCacheRecord, KnowledgeBaseRecord,
                                               KnowledgeChunkRecord, KnowledgeDocumentRecord,
                                               KnowledgeDocumentVersionRecord)
from . import config as graph_config
from . import llm
from .store import CommunityOut, EntityOut, GraphStore, RelationOut, SqlGraphStore, WrittenGraph, assign_ids

logger = logging.getLogger(__name__)

MAX_CHUNKS = 2000
MAX_REPORTS = 50
DEBOUNCE = timedelta(seconds=30)
LEASE = timedelta(minutes=30)
MAX_ATTEMPTS = 3
BACKOFF = (60, 300)
EMBED_BATCH = 32


def graph_collection(kb_id: str) -> str:
    return 'g' + kb_id.replace('-', '').lower()


def schedule(db: Session, kb: KnowledgeBaseRecord, user_id: UUID, *, delay: timedelta = DEBOUNCE) -> GraphBuildRecord | None:
    """Queue a build when the base indexes a graph; at most one pending build per base (it is pushed back).

    Called in the caller's transaction when documents change. Returns None for bases without a graph.
    """
    if not kb.indexing.get('graph'):
        return None
    try:
        config = graph_config.parse(kb.settings, require_available=False)
    except ValueError:
        return None
    now = utc_now()
    pending = db.scalar(select(GraphBuildRecord).where(GraphBuildRecord.kb_id == kb.id,
                                                       GraphBuildRecord.state == 'pending'))
    if pending is not None:
        pending.available_at, pending.updated_at = now + delay, now
        pending.mode, pending.store = config.mode, config.store
        return pending
    build = GraphBuildRecord(id=new_id(), tenant_id=kb.tenant_id, kb_id=kb.id, mode=config.mode, store=config.store,
                             state='pending', stage='', progress={}, version_ids=[], attempts=0,
                             available_at=now + delay, created_by=kb.created_by, created_at=now, updated_at=now)
    db.add(build)
    return build


def store_for(factory: sessionmaker[Session], store: str, tenant_id: UUID | None = None) -> GraphStore:
    """The graph store a base writes to: ``builtin`` or a registered store of the same space."""
    if store == 'builtin':
        return SqlGraphStore(factory)
    try:
        store_id = UUID(store)
    except ValueError:
        raise ValueError('unknown graph store') from None
    with factory() as db:
        row = db.get(GraphStoreRecord, store_id)
        if row is None or (tenant_id is not None and row.tenant_id != tenant_id):
            raise NotFound('Graph store not found')
        engine, config = row.engine, stores.reveal_config(row.id, row.connection_config)
    capabilities.require_available('graph_store', engine)
    if engine == 'neo4j':
        from .neo4j import Neo4jGraphStore
        return Neo4jGraphStore(config)
    raise NotImplementedError(f'graph store engine {engine} has no implementation')


def claim(factory: sessionmaker[Session], limit: int = 1) -> list[UUID]:
    now = utc_now()
    with factory() as db, db.begin():
        rows = db.scalars(select(GraphBuildRecord).where(
            GraphBuildRecord.state.in_(('pending', 'running')), GraphBuildRecord.available_at <= now)
            .order_by(GraphBuildRecord.available_at).limit(limit).with_for_update(skip_locked=True)).all()
        for build in rows:
            build.state, build.available_at, build.updated_at = 'running', now + LEASE, now
        return [b.id for b in rows]


async def run_due(factory: sessionmaker[Session], limit: int = 1) -> int:
    ids = claim(factory, limit)
    for build_id in ids:
        await run_build(factory, build_id)
    return len(ids)


def _progress(factory, build_id: UUID, stage: str, **progress) -> None:
    with factory() as db, db.begin():
        build = db.get(GraphBuildRecord, build_id)
        if build is not None:
            build.stage, build.progress = stage, {**(build.progress or {}), **progress}
            build.available_at, build.updated_at = utc_now() + LEASE, utc_now()


async def run_build(factory: sessionmaker[Session], build_id: UUID) -> str:
    try:
        await _build(factory, build_id)
        return 'ready'
    except _Cancelled:
        return 'cancelled'
    except _Deferred:
        with factory() as db, db.begin():
            build = db.get(GraphBuildRecord, build_id)
            if build is not None and build.state == 'running':
                build.state, build.available_at, build.updated_at = 'pending', utc_now() + DEBOUNCE, utc_now()
        return 'pending'
    except Exception as exc:
        message = f'{type(exc).__name__}: {exc}'[:1000]
        logger.warning('graph build failed', extra={'build_id': str(build_id), 'error': type(exc).__name__})
        with factory() as db, db.begin():
            build = db.get(GraphBuildRecord, build_id)
            if build is None:
                return 'missing'
            build.attempts += 1
            build.error, build.updated_at = message, utc_now()
            if build.attempts >= MAX_ATTEMPTS or isinstance(exc, PERMANENT):
                build.state = 'failed'
                return 'failed'
            build.state = 'pending'
            build.available_at = utc_now() + timedelta(seconds=BACKOFF[min(build.attempts - 1, len(BACKOFF) - 1)])
            return 'pending'


# Configuration, authorization and wiring errors do not heal by retrying.
PERMANENT = (ValueError, PlatformError, LookupError, NotImplementedError)


class _Cancelled(Exception):
    pass


class _Deferred(Exception):
    """Documents of the base are still being indexed; build later so the graph sees all their chunks."""


def _current(factory, build_id: UUID):
    """The build, its base and the chunks of the base's current document versions (id, version, text)."""
    with factory() as db:
        build = db.get(GraphBuildRecord, build_id)
        kb = db.get(KnowledgeBaseRecord, build.kb_id) if build else None
        if build is None or kb is None or kb.status != 'active' or build.state not in ('pending', 'running'):
            raise _Cancelled()
        config = graph_config.parse(kb.settings)
        if db.scalar(select(KnowledgeDocumentVersionRecord.id).where(
                KnowledgeDocumentVersionRecord.kb_id == kb.id,
                KnowledgeDocumentVersionRecord.state.in_(('pending', 'parsed', 'embedded'))).limit(1)) is not None:
            raise _Deferred()
        rows = db.execute(select(KnowledgeChunkRecord.id, KnowledgeChunkRecord.version_id,
                                 KnowledgeChunkRecord.content).join(
            KnowledgeDocumentRecord, KnowledgeDocumentRecord.current_version_id == KnowledgeChunkRecord.version_id)
            .where(KnowledgeDocumentRecord.kb_id == kb.id, KnowledgeDocumentRecord.status == 'active')
            .order_by(KnowledgeChunkRecord.version_id, KnowledgeChunkRecord.ordinal)).all()
        return build, kb, config, [(str(c), str(v), text) for c, v, text in rows]


async def _build(factory, build_id: UUID) -> None:
    build, kb, config, chunks = _current(factory, build_id)
    tenant_id, owner_id, kb_id, mode = kb.tenant_id, kb.created_by, kb.id, config.mode
    truncated = len(chunks) > MAX_CHUNKS
    chunks = chunks[:MAX_CHUNKS]
    model_key = str(config.model_id)

    # 1. extract (cached per chunk)
    extractions: list[tuple[merge.Source, extract.Extraction]] = []
    fresh = 0
    for index, (chunk_id, version_id, text) in enumerate(chunks):
        key = extract.cache_key(text, config.schema, model_key, mode)
        with factory() as db:
            cached = db.scalar(select(GraphExtractionCacheRecord.result).where(
                GraphExtractionCacheRecord.kb_id == kb_id, GraphExtractionCacheRecord.cache_key == key))
        if cached is not None:
            result = extract.Extraction.from_json(cached)
        else:
            reply = await llm.complete(factory, tenant_id, owner_id, config.model_id, 'knowledge.graph',
                                       extract.SYSTEM_PROMPT, extract.build_user_message(text, config.schema), 2000)
            result = extract.parse_extraction(reply, config.schema)
            with factory() as db, db.begin():
                if db.scalar(select(GraphExtractionCacheRecord.id).where(
                        GraphExtractionCacheRecord.kb_id == kb_id, GraphExtractionCacheRecord.cache_key == key)) is None:
                    db.add(GraphExtractionCacheRecord(id=new_id(), kb_id=kb_id, cache_key=key,
                                                      result=result.to_json(), created_at=utc_now()))
            fresh += 1
        extractions.append((merge.Source(chunk_id, version_id), result))
        if index % 5 == 4 or index == len(chunks) - 1:
            _progress(factory, build_id, 'extract', done=index + 1, total=len(chunks), model_calls=fresh,
                      truncated=truncated)

    # 2-3. merge, communities, reports
    _progress(factory, build_id, 'merge')
    graph = merge.merge(extractions)
    communities, reports = [], []
    if mode == 'graphrag_general':
        _progress(factory, build_id, 'communities')
        found = community_rules.detect(graph)
        found.sort(key=lambda c: (c.level, -len(c.members)))
        for number, item in enumerate(found[:MAX_REPORTS]):
            reply = await llm.complete(factory, tenant_id, owner_id, config.model_id, 'knowledge.graph',
                                       community_rules.REPORT_PROMPT, community_rules.build_report_message(graph, item), 1200)
            title, summary = community_rules.parse_report(reply)
            if summary:
                communities.append(item)
                reports.append((title, summary))
            _progress(factory, build_id, 'reports', done=number + 1, total=min(len(found), MAX_REPORTS))
    written = assign_ids(graph, communities, reports)

    # 4. write, 5. index
    _progress(factory, build_id, 'write')
    graph_store = store_for(factory, config.store, tenant_id)
    try:
        await graph_store.write(str(build_id), str(kb_id), written)
    finally:
        await graph_store.close()
    _progress(factory, build_id, 'index')
    await _index(factory, build_id, written)

    # 6. activate
    versions = sorted({v for _, v, _ in chunks})
    superseded: list[UUID] = []
    with factory() as db, db.begin():
        current = db.get(GraphBuildRecord, build_id)
        if current is None or current.state != 'running':
            raise _Cancelled()
        for old in db.scalars(select(GraphBuildRecord).where(
                GraphBuildRecord.kb_id == kb_id, GraphBuildRecord.state == 'ready', GraphBuildRecord.id != build_id)):
            old.state, old.updated_at = 'superseded', utc_now()
            superseded.append(old.id)
        current.state, current.stage, current.error, current.version_ids = 'ready', 'done', None, versions
        current.entity_count, current.relation_count = len(written.entities), len(written.relations)
        current.community_count, current.updated_at = len(written.communities), utc_now()
    for old_id in superseded:
        await _drop(factory, kb_id, old_id, config.store, tenant_id)


async def _drop(factory, kb_id: UUID, build_id: UUID, store: str, tenant_id: UUID) -> None:
    graph_store = store_for(factory, store, tenant_id)
    try:
        await graph_store.delete(str(build_id))
    finally:
        await graph_store.close()
    with factory() as db:
        kb = db.get(KnowledgeBaseRecord, kb_id)
        index = stores.vector_index_for(db, kb) if kb else None
    if index is not None:
        try:
            await index.delete_versions(graph_collection(str(kb_id)), [str(build_id)])
        finally:
            await index.close()


def _rows(written: WrittenGraph, kb_id: str, build_id: str):
    """Index documents of a written graph: (id, text) with ``e:``, ``r:``, ``c:`` id prefixes."""
    names = {e.id: e.name for e in written.entities}
    for e in written.entities:
        yield f'e:{e.id}', f'{e.name} {e.type} {e.description}'
    for r in written.relations:
        yield f'r:{r.id}', f'{names.get(r.source_id, "")} {names.get(r.target_id, "")} {r.description} ' + ' '.join(r.keywords)
    for c in written.communities:
        yield f'c:{c.id}', f'{c.title} {c.summary}'


async def _index(factory, build_id: UUID, written: WrittenGraph) -> None:
    with factory() as db:
        build = db.get(GraphBuildRecord, build_id)
        kb = db.get(KnowledgeBaseRecord, build.kb_id)
        index = stores.vector_index_for(db, kb)
        use_vectors = bool(kb.indexing.get('vector')) and kb.embedding_model_version_id is not None
        ids = (kb.id, kb.tenant_id, kb.created_by, kb.embedding_model_version_id)
    kb_id, tenant_id, owner_id, model_id = ids
    docs = list(_rows(written, str(kb_id), str(build_id)))
    collection = graph_collection(str(kb_id))
    try:
        for start in range(0, len(docs), EMBED_BATCH):
            batch = docs[start:start + EMBED_BATCH]
            vectors: list = [None] * len(batch)
            dimension = None
            if use_vectors:
                client = embedding.embedder(factory, tenant_id, owner_id, model_id, 'knowledge.embedding')
                try:
                    vectors = await client.embed([text for _, text in batch])
                finally:
                    await client.close()
                dimension = len(vectors[0]) if vectors and vectors[0] else None
            await index.upsert(collection, [IndexRow(item_id, str(kb_id), str(build_id), tokenize(text), vector)
                                            for (item_id, text), vector in zip(batch, vectors)], dimension=dimension)
    finally:
        await index.close()
