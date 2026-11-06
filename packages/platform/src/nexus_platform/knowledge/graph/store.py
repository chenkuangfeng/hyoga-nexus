"""Graph store port and the builtin SQL store (openspec 2026-11-06-knowledge-base, decision 2).

``builtin`` keeps entities, relations and communities in the platform database (RAGFlow keeps them next to the
chunks; no graph database to deploy). ``neo4j`` is an external store with the same port (K2.7). Every element
belongs to one build; a build is visible only while it is the newest ``ready`` build of its knowledge base, and
every element records the document versions it came from so search can drop what a newer document version
replaced.
"""
from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, sessionmaker

from nexus_core.platform import new_id
from nexus_knowledge.graph.merge import Graph, Source
from nexus_platform.persistence.models import (GraphCommunityRecord, GraphEntityRecord, GraphRelationRecord)


@dataclass
class EntityOut:
    id: str
    name: str
    type: str
    description: str
    sources: tuple[tuple[str, str], ...]  # (chunk_id, version_id)
    degree: int = 0

    @property
    def versions(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(v for _, v in self.sources))


@dataclass
class RelationOut:
    id: str
    source_id: str
    target_id: str
    description: str
    keywords: tuple[str, ...]
    weight: float
    sources: tuple[tuple[str, str], ...]

    @property
    def versions(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(v for _, v in self.sources))


@dataclass
class CommunityOut:
    id: str
    level: int
    entity_ids: tuple[str, ...]
    title: str
    summary: str
    sources: tuple[tuple[str, str], ...] = ()

    @property
    def versions(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(v for _, v in self.sources))


@dataclass
class WrittenGraph:
    entities: list[EntityOut] = field(default_factory=list)
    relations: list[RelationOut] = field(default_factory=list)
    communities: list[CommunityOut] = field(default_factory=list)


def _pairs(sources) -> tuple[tuple[str, str], ...]:
    """``(chunk_id, version_id)`` pairs of merged ``Source`` objects or stored dicts, without duplicates."""
    return tuple(dict.fromkeys(
        (s['chunk_id'], s['version_id']) if isinstance(s, dict) else (s.chunk_id, s.version_id) for s in sources))


def _stored(pairs) -> list[dict[str, str]]:
    return [{'chunk_id': c, 'version_id': v} for c, v in pairs][:40]


def assign_ids(graph: Graph, communities, reports) -> WrittenGraph:
    """Give every merged element an id (pure; the store only persists)."""
    out = WrittenGraph()
    ids: dict[str, str] = {}
    for key in sorted(graph.entities):
        entity = graph.entities[key]
        ids[key] = str(new_id())
        out.entities.append(EntityOut(ids[key], entity.name, entity.type, entity.description,
                                      _pairs(entity.sources), entity.degree))
    for (a, b), relation in sorted(graph.relations.items()):
        out.relations.append(RelationOut(str(new_id()), ids[a], ids[b], relation.description,
                                         tuple(relation.keywords), relation.weight, _pairs(relation.sources)))
    for community, (title, summary) in zip(communities, reports):
        members = [graph.entities[k] for k in community.members]
        sources = [s for m in members for s in m.sources]
        out.communities.append(CommunityOut(str(new_id()), community.level, tuple(ids[k] for k in community.members),
                                            title, summary, _pairs(sources)[:20]))
    return out


class GraphStore(ABC):
    """Persistence of one graph build. Methods are safe to call from several requests."""

    engine = ''

    @abstractmethod
    async def write(self, build_id: str, kb_id: str, graph: WrittenGraph) -> None: ...

    @abstractmethod
    async def delete(self, build_id: str) -> None: ...

    @abstractmethod
    async def entities(self, build_id: str, ids: list[str]) -> list[EntityOut]: ...

    @abstractmethod
    async def match_names(self, build_id: str, norms: list[str], limit: int) -> list[EntityOut]:
        """Entities whose normalized name equals one of ``norms`` (exact; the entity-lookup tool)."""

    @abstractmethod
    async def edges(self, build_id: str, entity_ids: list[str]) -> list[RelationOut]:
        """Relations that touch any of ``entity_ids``."""

    @abstractmethod
    async def relations(self, build_id: str, ids: list[str]) -> list[RelationOut]: ...

    @abstractmethod
    async def communities(self, build_id: str, ids: list[str]) -> list[CommunityOut]: ...

    @abstractmethod
    async def community_ids_of(self, build_id: str, entity_ids: list[str], limit: int) -> list[str]: ...


class SqlGraphStore(GraphStore):
    engine = 'builtin'

    def __init__(self, factory: sessionmaker[Session]) -> None:
        self.factory = factory

    async def _run(self, fn):
        return await asyncio.to_thread(fn)

    async def write(self, build_id: str, kb_id: str, graph: WrittenGraph) -> None:
        def work():
            from nexus_platform.knowledge.graph.norm import norm_name
            bid, kid = UUID(build_id), UUID(kb_id)
            with self.factory() as db, db.begin():
                db.add_all([GraphEntityRecord(
                    id=UUID(e.id), build_id=bid, kb_id=kid, name=e.name, norm=norm_name(e.name), entity_type=e.type,
                    description=e.description,
                    sources=_stored(e.sources), degree=e.degree) for e in graph.entities])
                db.add_all([GraphRelationRecord(
                    id=UUID(r.id), build_id=bid, kb_id=kid, source_id=UUID(r.source_id), target_id=UUID(r.target_id),
                    description=r.description, keywords=list(r.keywords), weight=r.weight,
                    sources=_stored(r.sources))
                    for r in graph.relations])
                db.add_all([GraphCommunityRecord(
                    id=UUID(c.id), build_id=bid, kb_id=kid, level=c.level, entity_ids=list(c.entity_ids),
                    title=c.title, summary=c.summary,
                    sources=_stored(c.sources))
                    for c in graph.communities])
        await self._run(work)

    async def delete(self, build_id: str) -> None:
        def work():
            bid = UUID(build_id)
            with self.factory() as db, db.begin():
                for model in (GraphCommunityRecord, GraphRelationRecord, GraphEntityRecord):
                    db.execute(model.__table__.delete().where(model.build_id == bid))
        await self._run(work)

    @staticmethod
    def _entity(row: GraphEntityRecord) -> EntityOut:
        return EntityOut(str(row.id), row.name, row.entity_type, row.description, _pairs(row.sources),
                         row.degree)

    @staticmethod
    def _relation(row: GraphRelationRecord) -> RelationOut:
        return RelationOut(str(row.id), str(row.source_id), str(row.target_id), row.description, tuple(row.keywords),
                           row.weight, _pairs(row.sources))

    async def entities(self, build_id: str, ids: list[str]) -> list[EntityOut]:
        def work():
            with self.factory() as db:
                rows = db.scalars(select(GraphEntityRecord).where(
                    GraphEntityRecord.build_id == UUID(build_id), GraphEntityRecord.id.in_([UUID(i) for i in ids]))).all()
                by_id = {str(r.id): self._entity(r) for r in rows}
            return [by_id[i] for i in ids if i in by_id]
        return await self._run(work) if ids else []

    async def match_names(self, build_id: str, norms: list[str], limit: int) -> list[EntityOut]:
        def work():
            with self.factory() as db:
                rows = db.scalars(select(GraphEntityRecord).where(
                    GraphEntityRecord.build_id == UUID(build_id), GraphEntityRecord.norm.in_(norms))
                    .order_by(GraphEntityRecord.degree.desc(), GraphEntityRecord.id).limit(limit)).all()
                return [self._entity(r) for r in rows]
        return await self._run(work) if norms else []

    async def edges(self, build_id: str, entity_ids: list[str]) -> list[RelationOut]:
        def work():
            ids = [UUID(i) for i in entity_ids]
            with self.factory() as db:
                rows = db.scalars(select(GraphRelationRecord).where(
                    GraphRelationRecord.build_id == UUID(build_id),
                    or_(GraphRelationRecord.source_id.in_(ids), GraphRelationRecord.target_id.in_(ids)))).all()
                return [self._relation(r) for r in rows]
        return await self._run(work) if entity_ids else []

    async def relations(self, build_id: str, ids: list[str]) -> list[RelationOut]:
        def work():
            with self.factory() as db:
                rows = db.scalars(select(GraphRelationRecord).where(
                    GraphRelationRecord.build_id == UUID(build_id),
                    GraphRelationRecord.id.in_([UUID(i) for i in ids]))).all()
                by_id = {str(r.id): self._relation(r) for r in rows}
            return [by_id[i] for i in ids if i in by_id]
        return await self._run(work) if ids else []

    async def communities(self, build_id: str, ids: list[str]) -> list[CommunityOut]:
        def work():
            with self.factory() as db:
                rows = db.scalars(select(GraphCommunityRecord).where(
                    GraphCommunityRecord.build_id == UUID(build_id),
                    GraphCommunityRecord.id.in_([UUID(i) for i in ids]))).all()
                by_id = {str(r.id): CommunityOut(str(r.id), r.level, tuple(r.entity_ids), r.title, r.summary,
                                                  _pairs(r.sources)) for r in rows}
            return [by_id[i] for i in ids if i in by_id]
        return await self._run(work) if ids else []

    async def community_ids_of(self, build_id: str, entity_ids: list[str], limit: int) -> list[str]:
        def work():
            wanted = set(entity_ids)
            with self.factory() as db:
                rows = db.scalars(select(GraphCommunityRecord).where(
                    GraphCommunityRecord.build_id == UUID(build_id))
                    .order_by(GraphCommunityRecord.level.desc(), GraphCommunityRecord.id)).all()
                scored = [(len(wanted & set(r.entity_ids)), str(r.id)) for r in rows]
            scored = [item for item in scored if item[0] > 0]
            scored.sort(key=lambda item: (-item[0], item[1]))
            return [cid for _, cid in scored[:limit]]
        return await self._run(work)
