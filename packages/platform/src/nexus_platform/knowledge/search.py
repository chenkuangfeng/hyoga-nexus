"""Pre-Filter and hybrid search (openspec 2026-11-06-knowledge-base K1.7, architecture 2.10).

1. :func:`resolve_scope` computes, at call time, the knowledge bases the caller may read from the current
   space (optionally limited to an agent's bound bases and then to a requested subset) and, for each, the
   current version ids of its active documents. Nothing is searched outside this scope.
2. Per base, the keyword channel (when the base indexes keywords and the engine supports it) and the vector
   channel (when the base indexes vectors and the query can be embedded) run on the base's vector store with
   the scope pushed down to the engine.
3. All lists are fused (weighted RRF, :mod:`nexus_knowledge.retrieval.fuse`). Hits are loaded from the
   platform database and filtered by the scope once more (defense in depth).

Degradation: a failing vector channel (no embedding model, the user cannot use it, provider or engine error)
is dropped for that base and reported in ``degraded``; a failing keyword channel likewise. Each degradation is
audited as ``knowledge.search_degraded``. A degradation never widens the scope.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from nexus_knowledge.index import Scope, VectorStoreError, collection_name
from nexus_knowledge.retrieval.fuse import Candidate, fuse
from nexus_knowledge.retrieval import synonyms
from nexus_knowledge.text import query_tokens
from nexus_platform.authz.audit import audit
from nexus_platform.persistence.models import (FaqEntryRecord, KnowledgeBaseRecord, KnowledgeChunkRecord, KnowledgeDocumentRecord,
                                               KnowledgeDocumentVersionRecord)
from . import access, embedding, stores
from . import faq as faq_rules
from .organize import DocumentFilter

logger = logging.getLogger(__name__)

MAX_LIMIT = 50
CANDIDATES_PER_CHANNEL = 30


@dataclass
class ScopedBase:
    kb: KnowledgeBaseRecord
    version_ids: tuple[str, ...]


@dataclass
class SearchHit:
    chunk_id: str
    score: float
    ranks: dict[str, int]
    content: str
    kb_id: str
    kb_name: str
    document_id: str
    filename: str
    version_id: str
    ordinal: int
    page: int | None
    section: list[str]

    def ref(self) -> dict[str, Any]:
        """Citation reference kept by the evidence registry."""
        return {'kb_id': self.kb_id, 'document_id': self.document_id, 'version_id': self.version_id,
                'filename': self.filename, 'page': self.page, 'section': self.section, 'ordinal': self.ordinal}


@dataclass
class SearchResult:
    hits: list[SearchHit]
    degraded: list[dict[str, str]] = field(default_factory=list)
    searched: list[str] = field(default_factory=list)
    ignored: list[str] = field(default_factory=list)


def resolve_scope(db: Session, tenant_id: UUID, user_id: UUID, *, bound: Sequence[UUID] | None = None,
                  requested: Sequence[UUID] | None = None, doc_filter: DocumentFilter | None = None) -> tuple[list[ScopedBase], list[str]]:
    """Readable bases with their searchable versions; second value lists requested ids that were ignored.

    ``bound`` restricts to an agent version's bindings (None: every readable base, used by the management
    UI); ``requested`` narrows further and can never add a base.
    """
    allowed = list(bound) if bound is not None else None
    ignored: list[str] = []
    if requested:
        wanted = list(dict.fromkeys(requested))
        if allowed is not None:
            ignored = [str(i) for i in wanted if i not in set(allowed)]
            wanted = [i for i in wanted if i in set(allowed)]
        allowed = wanted
    bases = access.readable_bases(db, tenant_id, user_id, allowed)
    if requested:
        found = {kb.id for kb in bases}
        ignored += [str(i) for i in requested if i not in found and str(i) not in ignored]
    out = []
    for kb in bases:
        if kb.kb_type == 'faq':
            # FAQ entries play the role of versions; a tag filter keeps only entries with a wanted tag.
            ids = faq_rules.scope_ids(db, kb.id, doc_filter.tag_ids if doc_filter and doc_filter.tag_ids else None)
            out.append(ScopedBase(kb, () if doc_filter and (doc_filter.folder is not None or doc_filter.metadata) else ids))
            continue
        docs = db.scalars(select(KnowledgeDocumentRecord).where(
            KnowledgeDocumentRecord.kb_id == kb.id, KnowledgeDocumentRecord.status == 'active',
            KnowledgeDocumentRecord.current_version_id.is_not(None))).all()
        if doc_filter is not None and not doc_filter.empty():
            docs = [d for d in docs if doc_filter.matches(d)]
        out.append(ScopedBase(kb, tuple(sorted(str(d.current_version_id) for d in docs))))
    return out, ignored


async def search(factory: sessionmaker[Session], db: Session, tenant_id: UUID, user_id: UUID, query: str, *,
                 limit: int = 8, bound: Sequence[UUID] | None = None, requested: Sequence[UUID] | None = None,
                 vector_weight: float = 1.0, keyword_weight: float = 1.0,
                 doc_filter: DocumentFilter | None = None) -> SearchResult:
    """Search the caller's readable scope. ``db`` is used for reads only; audits are written in it too."""
    query = (query or '').strip()
    if not query:
        raise ValueError('query must not be empty')
    limit = max(1, min(int(limit), MAX_LIMIT))
    scoped, ignored = resolve_scope(db, tenant_id, user_id, bound=bound, requested=requested, doc_filter=doc_filter)
    result = SearchResult(hits=[], ignored=ignored)
    tokens = query_tokens(query)
    vector_lists: list[list[Candidate]] = []
    keyword_lists: list[list[Candidate]] = []
    query_vectors: dict[UUID, list[float] | Exception] = {}
    for item in scoped:
        kb = item.kb
        result.searched.append(str(kb.id))
        if not item.version_ids:
            continue
        scope = Scope(str(kb.id), item.version_ids)
        collection = collection_name(str(kb.id))
        # The base's synonym groups widen the keyword query only (the vector query is the user's own text).
        try:
            extra = synonyms.expand(query, synonyms.parse((kb.settings or {}).get('synonyms')))
        except ValueError:
            extra = []
        kb_tokens = query_tokens(query + ' ' + ' '.join(extra)) if extra else tokens
        try:
            index = stores.vector_index_for(db, kb)
        except Exception as exc:  # unusable store configuration: nothing can be searched in this base
            _degrade(db, result, tenant_id, user_id, kb, 'all', 'store_unavailable', exc)
            continue
        try:
            if kb.indexing.get('keyword') and index.supports_keyword and kb_tokens:
                try:
                    keyword_lists.append(await index.search_keyword(collection, kb_tokens, scope, CANDIDATES_PER_CHANNEL))
                except VectorStoreError as exc:
                    _degrade(db, result, tenant_id, user_id, kb, 'keyword', exc.code, exc)
            if kb.indexing.get('vector'):
                vector = await _query_vector(factory, tenant_id, user_id, kb, query, query_vectors)
                if isinstance(vector, Exception):
                    _degrade(db, result, tenant_id, user_id, kb, 'vector', _reason(vector), vector)
                elif kb.embedding_dimension and len(vector) != kb.embedding_dimension:
                    _degrade(db, result, tenant_id, user_id, kb, 'vector', 'dimension_mismatch', None)
                else:
                    try:
                        vector_lists.append(await index.search_vector(collection, vector, scope, CANDIDATES_PER_CHANNEL))
                    except VectorStoreError as exc:
                        _degrade(db, result, tenant_id, user_id, kb, 'vector', exc.code, exc)
        finally:
            await index.close()
    fused = fuse(vector_lists, keyword_lists, vector_weight=vector_weight, keyword_weight=keyword_weight)
    result.hits = _load_hits(db, fused, scoped, limit, query)
    return result


def _reason(exc: Exception) -> str:
    if isinstance(exc, LookupError):
        return 'embedding_unavailable'
    return getattr(exc, 'code', None) or 'embedding_failed'


async def _query_vector(factory, tenant_id: UUID, user_id: UUID, kb: KnowledgeBaseRecord, query: str,
                        cache: dict[UUID, list[float] | Exception]) -> list[float] | Exception:
    """The query embedded with the caller's own key (decision 6), once per embedding model."""
    model = kb.embedding_model_version_id
    if model is None:
        return LookupError('no embedding model')
    if model not in cache:
        try:
            client = embedding.embedder(factory, tenant_id, user_id, model, 'knowledge.query')
            try:
                (vector,) = await client.embed([query])
            finally:
                await client.close()
            cache[model] = [float(x) for x in vector]
        except Exception as exc:  # provider or authorization failure: keyword search still answers
            cache[model] = exc
    return cache[model]


def _degrade(db: Session, result: SearchResult, tenant_id: UUID, user_id: UUID, kb: KnowledgeBaseRecord,
             channel: str, reason: str, exc: Exception | None) -> None:
    result.degraded.append({'kb_id': str(kb.id), 'channel': channel, 'reason': reason})
    logger.warning('knowledge search degraded', extra={'kb_id': str(kb.id), 'channel': channel, 'reason': reason,
                                                       'error': type(exc).__name__ if exc else None})
    audit(db, tenant_id, user_id, 'knowledge.search_degraded', access.KIND, str(kb.id),
          {'channel': channel, 'reason': reason})


def _resolve_question_rows(fused):
    """Rows of generated questions (``q:<chunk>:<n>``) stand for their chunk; the best-ranked row of a chunk wins."""
    out, seen = [], set()
    for item in fused:
        if item.chunk_id.startswith('q:'):
            parts = item.chunk_id.split(':')
            if len(parts) < 3:
                continue
            item = type(item)(parts[1], item.score, {**item.ranks, 'question': 1})
        if item.chunk_id in seen:
            continue
        seen.add(item.chunk_id)
        out.append(item)
    return out


def _load_hits(db: Session, fused, scoped: list[ScopedBase], limit: int, query: str = '') -> list[SearchHit]:
    allowed = {version for item in scoped for version in item.version_ids}
    names = {item.kb.id: item.kb.name for item in scoped}
    fused = _resolve_question_rows(fused)
    ids, faq_ids = [], []
    for item in fused:
        if item.chunk_id.startswith('f:'):
            try:
                faq_ids.append(UUID(item.chunk_id.split(':')[1]))
            except (ValueError, IndexError):
                pass
            continue
        try:
            ids.append(UUID(item.chunk_id))
        except ValueError:
            continue
    by_id: dict = {}
    if ids:
        rows = db.execute(select(KnowledgeChunkRecord, KnowledgeDocumentVersionRecord, KnowledgeDocumentRecord).join(
            KnowledgeDocumentVersionRecord, KnowledgeDocumentVersionRecord.id == KnowledgeChunkRecord.version_id).join(
            KnowledgeDocumentRecord, KnowledgeDocumentRecord.id == KnowledgeDocumentVersionRecord.document_id).where(
            KnowledgeChunkRecord.id.in_(ids[: limit * 4]))).all()
        by_id = {str(chunk.id): (chunk, version, doc) for chunk, version, doc in rows}
    faq_by_id = {}
    if faq_ids:
        faq_by_id = {str(e.id): e for e in db.scalars(select(FaqEntryRecord).where(
            FaqEntryRecord.id.in_(faq_ids), FaqEntryRecord.status == 'active', FaqEntryRecord.enabled.is_(True),
            FaqEntryRecord.index_state == 'ready'))}
    parents = {}
    parent_ids = {c.parent_id for c, _, _ in by_id.values() if c.parent_id is not None}
    if parent_ids:
        parents = {p.id: p for p in db.scalars(select(KnowledgeChunkRecord).where(KnowledgeChunkRecord.id.in_(parent_ids)))}
    hits, seen_entries, seen_parents = [], set(), set()
    for item in fused:
        if item.chunk_id.startswith('f:'):
            entry = faq_by_id.get(item.chunk_id.split(':')[1]) if item.chunk_id.count(':') >= 2 else None
            if entry is None or str(entry.id) not in allowed or str(entry.id) in seen_entries:
                continue
            if faq_rules.rules.negated(query, entry.negative_questions):  # the entry says it is not the answer
                continue
            seen_entries.add(str(entry.id))
            answer = faq_rules.rules.answer_text(entry.answers, entry.answer_strategy)
            hits.append(SearchHit(f'f:{entry.id}', round(item.score, 6), item.ranks,
                                  f'问：{entry.standard_question}\n答：{answer}', str(entry.kb_id),
                                  names.get(entry.kb_id, ''), str(entry.id), entry.standard_question, str(entry.id), 0,
                                  None, [entry.category] if entry.category else []))
        else:
            found = by_id.get(item.chunk_id)
            if found is None:
                continue
            chunk, version, doc = found
            if str(version.id) not in allowed or doc.status != 'active':  # stale index row or out of scope
                continue
            if chunk.parent_id is not None and chunk.parent_id in parents:
                # Parent-child chunking: the child matched, the model gets the larger parent (once).
                if chunk.parent_id in seen_parents:
                    continue
                seen_parents.add(chunk.parent_id)
                chunk = parents[chunk.parent_id]
                item = type(item)(str(chunk.id), item.score, item.ranks)
            hits.append(SearchHit(item.chunk_id, round(item.score, 6), item.ranks, chunk.content, str(doc.kb_id),
                                  names.get(doc.kb_id, ''), str(doc.id), doc.filename, str(version.id), chunk.ordinal,
                                  chunk.page, list(chunk.section)))
        if len(hits) >= limit:
            break
    return hits


def hit_view(hit: SearchHit) -> dict[str, Any]:
    return {'chunk_id': hit.chunk_id, 'score': hit.score, 'channels': hit.ranks, 'content': hit.content,
            'kb_id': hit.kb_id, 'kb_name': hit.kb_name, 'document_id': hit.document_id, 'filename': hit.filename,
            'version_id': hit.version_id, 'ordinal': hit.ordinal, 'page': hit.page, 'section': hit.section}
