"""Graph status and browsing for the management UI (openspec 2026-11-06-knowledge-base K2.6).

Everything here uses the same scope rules as search: elements whose source document versions are no longer
current and readable are not shown.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from nexus_core.platform import utc_now
from nexus_knowledge.graph.retrieve import Limits
from nexus_platform.errors import Conflict
from nexus_platform.persistence.models import GraphBuildRecord, GraphEntityRecord, KnowledgeBaseRecord
from nexus_platform.knowledge import access, search as base_search
from . import config as graph_config
from . import search as graph_search
from .build import schedule, store_for


def _build_view(build: GraphBuildRecord | None) -> dict[str, Any] | None:
    if build is None:
        return None
    return {'id': str(build.id), 'state': build.state, 'stage': build.stage, 'progress': build.progress,
            'mode': build.mode, 'entity_count': build.entity_count, 'relation_count': build.relation_count,
            'community_count': build.community_count, 'error': build.error, 'attempts': build.attempts,
            'created_at': build.created_at.isoformat(), 'updated_at': build.updated_at.isoformat()}


def status(db: Session, kb: KnowledgeBaseRecord) -> dict[str, Any]:
    """Configuration, the visible (ready) build and the newest unfinished or failed build."""
    ready = graph_search.ready_build(db, kb.id)
    latest = db.scalar(select(GraphBuildRecord).where(GraphBuildRecord.kb_id == kb.id)
                       .order_by(GraphBuildRecord.created_at.desc()).limit(1))
    raw = dict((kb.settings or {}).get('graph') or {})
    return {'enabled': bool(kb.indexing.get('graph')),
            'config': {'mode': raw.get('mode', 'graphrag_light'), 'store': raw.get('store', 'builtin'),
                       'model_id': raw.get('model_id'), 'entity_types': raw.get('entity_types', []),
                       'relation_types': raw.get('relation_types', []), 'instructions': raw.get('instructions', '')},
            'ready': _build_view(ready), 'latest': _build_view(latest if latest is not ready else None)}


def request_rebuild(db: Session, kb: KnowledgeBaseRecord, user_id: UUID) -> dict[str, Any]:
    if not kb.indexing.get('graph'):
        raise Conflict('Graph indexing is not enabled for this knowledge base')
    graph_config.parse(kb.settings)
    from datetime import timedelta
    build = schedule(db, kb, user_id, delay=timedelta(0))
    return _build_view(build) or {}


def cancel_failed(db: Session, kb: KnowledgeBaseRecord) -> None:
    for build in db.scalars(select(GraphBuildRecord).where(GraphBuildRecord.kb_id == kb.id,
                                                           GraphBuildRecord.state == 'failed')):
        build.state, build.updated_at = 'cancelled', utc_now()


async def overview(factory: sessionmaker[Session], db: Session, tenant_id: UUID, user_id: UUID, kb_id: UUID,
                   *, names: list[str], hops: int, limit: int) -> dict[str, Any]:
    """Nodes and edges to draw: the named entities with their neighbourhood, or the best-connected ones."""
    kb = access.readable_base(db, kb_id, tenant_id, user_id)
    scoped, _ = base_search.resolve_scope(db, tenant_id, user_id, requested=[kb_id])
    item = next((s for s in scoped if s.kb.id == kb.id), None)
    build = graph_search.ready_build(db, kb.id)
    if item is None or build is None:
        return {'nodes': [], 'edges': [], 'truncated': False, 'build': _build_view(build)}
    allowed = set(item.version_ids)
    limits = Limits(hops=max(1, min(hops, 3)), max_entities=max(5, min(limit, 200)), max_relations=max(5, min(limit * 2, 400)))
    if names:
        found = await graph_search.lookup_entities(factory, db, kb, build, allowed, names, limits)
    else:
        top = db.scalars(select(GraphEntityRecord).where(GraphEntityRecord.build_id == build.id)
                         .order_by(GraphEntityRecord.degree.desc(), GraphEntityRecord.id).limit(limits.max_entities)).all()
        seeds = [str(e.id) for e in top]
        found = graph_search.GraphResult(str(kb.id))
        found = await graph_search._expand(store_for(factory, build.store), str(build.id), found, seeds, [], allowed,
                                           Limits(hops=1, max_entities=limits.max_entities, max_relations=limits.max_relations))
    return {'nodes': [{'id': e.id, 'name': e.name, 'type': e.type, 'description': e.description, 'degree': e.degree}
                      for e in found.entities],
            'edges': [{'id': r.id, 'source': r.source_id, 'target': r.target_id, 'description': r.description,
                       'keywords': list(r.keywords), 'weight': r.weight} for r in found.relations],
            'communities': [{'id': c.id, 'level': c.level, 'title': c.title, 'summary': c.summary,
                             'size': len(c.entity_ids)} for c in found.communities],
            'truncated': found.truncated, 'build': _build_view(build)}
