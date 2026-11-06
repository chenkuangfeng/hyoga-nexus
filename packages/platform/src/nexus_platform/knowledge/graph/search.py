"""Graph search for ``search_knowledge`` and ``query_knowledge_graph`` (openspec 2026-11-06-knowledge-base K2.5).

Seeds come from the graph collection of the base's vector store (keyword channel always, vector channel when the
base has an embedding model and the caller can use it), restricted to the visible build by ``Scope``. The graph
is then expanded with hard limits (:mod:`nexus_knowledge.graph.retrieve`) and filtered to the caller's scope:
an element is visible only if one of its source document versions is still a current, readable version.
The result states when a limit cut the walk, and when the graph could not be used at all (``degraded``) so the
caller falls back to plain chunk search; graph failure never widens access and never blocks the answer.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from nexus_knowledge.graph import retrieve
from nexus_knowledge.graph.extract import norm
from nexus_knowledge.index import Scope, VectorStoreError
from nexus_knowledge.retrieval.fuse import Candidate, fuse
from nexus_knowledge.text import query_tokens
from nexus_platform.persistence.models import GraphBuildRecord, KnowledgeBaseRecord
from nexus_platform.knowledge import stores
from nexus_platform.knowledge.search import _query_vector
from .build import graph_collection, store_for
from .store import CommunityOut, EntityOut, RelationOut

logger = logging.getLogger(__name__)

SEEDS = 6
COMMUNITIES = 3
CANDIDATES = 20


@dataclass
class GraphResult:
    kb_id: str
    entities: list[EntityOut] = field(default_factory=list)
    relations: list[RelationOut] = field(default_factory=list)
    communities: list[CommunityOut] = field(default_factory=list)
    truncated: bool = False
    degraded: str = ''

    def empty(self) -> bool:
        return not (self.entities or self.relations or self.communities)


def ready_build(db: Session, kb_id: UUID) -> GraphBuildRecord | None:
    return db.scalar(select(GraphBuildRecord).where(GraphBuildRecord.kb_id == kb_id, GraphBuildRecord.state == 'ready')
                     .order_by(GraphBuildRecord.updated_at.desc()).limit(1))


def _visible(item, allowed: set[str]) -> bool:
    return any(v in allowed for v in item.versions)


async def search_graph(factory: sessionmaker[Session], db: Session, kb: KnowledgeBaseRecord, build: GraphBuildRecord,
                       allowed_versions: set[str], user_id: UUID, query: str, limits: retrieve.Limits,
                       query_cache: dict | None = None) -> GraphResult:
    """Graph context for ``query`` in one base. ``allowed_versions`` are the base's readable current versions."""
    result = GraphResult(str(kb.id))
    graph_store = store_for(factory, build.store, kb.tenant_id)
    collection = graph_collection(str(kb.id))
    scope = Scope(str(kb.id), (str(build.id),))
    tokens = query_tokens(query)
    try:
        index = stores.vector_index_for(db, kb)
    except Exception:
        result.degraded = 'store_unavailable'
        await graph_store.close()
        return result
    vector_lists, keyword_lists = [], []
    try:
        if index.supports_keyword and tokens:
            keyword_lists.append(await index.search_keyword(collection, tokens, scope, CANDIDATES))
        if kb.indexing.get('vector') and kb.embedding_model_version_id is not None:
            vector = await _query_vector(factory, kb.tenant_id, user_id, kb, query,
                                         query_cache if query_cache is not None else {})
            if not isinstance(vector, Exception) and (not kb.embedding_dimension or len(vector) == kb.embedding_dimension):
                vector_lists.append(await index.search_vector(collection, vector, scope, CANDIDATES))
    except VectorStoreError as exc:
        result.degraded = exc.code
        await graph_store.close()
        return result
    finally:
        await index.close()
    ranked = [item.chunk_id for item in fuse(vector_lists, keyword_lists)]
    entity_ids = [i[2:] for i in ranked if i.startswith('e:')][:SEEDS]
    relation_ids = [i[2:] for i in ranked if i.startswith('r:')][:SEEDS]
    community_ids = [i[2:] for i in ranked if i.startswith('c:')][:COMMUNITIES]
    seeds = list(entity_ids)
    if relation_ids:
        try:
            for relation in await graph_store.relations(str(build.id), relation_ids):
                if _visible(relation, allowed_versions):
                    seeds += [i for i in (relation.source_id, relation.target_id) if i not in seeds]
        except Exception:
            await graph_store.close()
            raise
    try:
        return await _expand(graph_store, str(build.id), result, seeds[:SEEDS * 2], community_ids, allowed_versions, limits)
    finally:
        await graph_store.close()


async def _expand(graph_store, build_id: str, result: GraphResult, seeds: list[str], community_ids: list[str],
                  allowed: set[str], limits: retrieve.Limits) -> GraphResult:
    edges: dict[str, list[tuple[str, str, float]]] = {}
    relations: dict[str, RelationOut] = {}
    frontier = list(seeds)
    known: set[str] = set()
    for _ in range(max(1, limits.hops)):
        todo = [i for i in frontier if i not in known]
        if not todo:
            break
        known.update(todo)
        found = await graph_store.edges(build_id, todo)
        next_ids = []
        for relation in found:
            if not _visible(relation, allowed) or relation.id in relations:
                continue
            relations[relation.id] = relation
            for here, there in ((relation.source_id, relation.target_id), (relation.target_id, relation.source_id)):
                edges.setdefault(here, []).append((relation.id, there, relation.weight))
                next_ids.append(there)
        frontier = next_ids
    expansion = retrieve.expand(seeds, edges, limits)
    result.truncated = expansion.truncated
    entities = {e.id: e for e in await graph_store.entities(build_id, expansion.entity_ids)}
    result.entities = [entities[i] for i in expansion.entity_ids if i in entities and _visible(entities[i], allowed)]
    shown = {e.id for e in result.entities}
    result.relations = [relations[i] for i in expansion.relation_ids
                        if i in relations and relations[i].source_id in shown and relations[i].target_id in shown]
    chosen = list(community_ids)
    for cid in await graph_store.community_ids_of(build_id, [e.id for e in result.entities], COMMUNITIES):
        if cid not in chosen:
            chosen.append(cid)
    result.communities = [c for c in await graph_store.communities(build_id, chosen[:COMMUNITIES + 2])
                          if _visible(c, allowed)][:COMMUNITIES]
    return result


async def lookup_entities(factory: sessionmaker[Session], db: Session, kb: KnowledgeBaseRecord,
                          build: GraphBuildRecord, allowed_versions: set[str], names: Sequence[str],
                          limits: retrieve.Limits) -> GraphResult:
    """``query_knowledge_graph``: exact normalized-name lookup, then bounded expansion."""
    result = GraphResult(str(kb.id))
    graph_store = store_for(factory, build.store, kb.tenant_id)
    try:
        matches = await graph_store.match_names(str(build.id), [norm(n) for n in names if norm(n)], limits.max_entities)
        seeds = [e.id for e in matches if _visible(e, allowed_versions)]
        if not seeds:
            return result
        return await _expand(graph_store, str(build.id), result, seeds, [], allowed_versions, limits)
    finally:
        await graph_store.close()
