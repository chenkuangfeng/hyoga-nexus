"""Neo4j graph store (K2.7; implemented without a real Neo4j, verified=false until one is available).

Uses the transactional HTTP API (``POST /db/{database}/tx/commit``), so no driver dependency is added.
Layout (WeKnora keeps a similar entity/relation graph in Neo4j):

- ``(:KGEntity {id, build_id, kb_id, name, norm, type, description, sources, degree})``
- ``(:KGEntity)-[:KG_REL {id, build_id, kb_id, description, keywords, weight, sources}]->(:KGEntity)``
- ``(:KGCommunity {id, build_id, kb_id, level, entity_ids, title, summary, sources})``

``sources`` is a JSON text of ``[[chunk_id, version_id], ...]``. Every query is filtered by ``build_id``; the
platform decides which build (and thus which knowledge base) a caller may read before any query runs, and the
caller filters results by readable document versions again. ``connection_config``: ``{"url":
"http://host:7474", "username": "...", "password": "...", "database": "neo4j", "verify_tls": true}``.
"""
from __future__ import annotations

import json
from typing import Any, Mapping

import httpx

from nexus_knowledge import capabilities
from .store import CommunityOut, EntityOut, GraphStore, RelationOut, WrittenGraph

BATCH = 500


class Neo4jError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _sources(raw: str | None) -> tuple[tuple[str, str], ...]:
    try:
        return tuple((c, v) for c, v in json.loads(raw or '[]'))
    except (TypeError, ValueError):
        return ()


def _dump(sources) -> str:
    return json.dumps([list(pair) for pair in sources][:40])


class Neo4jGraphStore(GraphStore):
    engine = 'neo4j'

    def __init__(self, connection: Mapping[str, Any]) -> None:
        url = str(connection.get('url') or '').rstrip('/')
        if not url:
            raise Neo4jError('invalid_config', 'neo4j graph store needs a url')
        auth = (str(connection['username']), str(connection.get('password') or '')) if connection.get('username') else None
        self.database = str(connection.get('database') or 'neo4j')
        self._client = httpx.AsyncClient(base_url=url, auth=auth, timeout=60.0,
                                         verify=bool(connection.get('verify_tls', True)),
                                         headers={'Accept': 'application/json;charset=UTF-8'})

    async def run(self, statement: str, **parameters: Any) -> list[dict[str, Any]]:
        try:
            response = await self._client.post(f'/db/{self.database}/tx/commit', json={
                'statements': [{'statement': statement, 'parameters': parameters,
                                'resultDataContents': ['row']}]})
        except httpx.HTTPError as exc:
            raise Neo4jError('connection_failed', type(exc).__name__) from exc
        if response.status_code >= 400:
            raise Neo4jError(f'http_{response.status_code}', response.text[:300])
        body = response.json()
        if body.get('errors'):
            first = body['errors'][0]
            raise Neo4jError(str(first.get('code', 'neo4j_error')), str(first.get('message', ''))[:300])
        result = body['results'][0]
        return [dict(zip(result['columns'], item['row'])) for item in result['data']]

    async def ping(self) -> dict[str, Any]:
        rows = await self.run('CALL dbms.components() YIELD name, versions RETURN name, versions')
        return {'engine': 'neo4j', 'components': rows}

    async def close(self) -> None:
        await self._client.aclose()

    async def write(self, build_id: str, kb_id: str, graph: WrittenGraph) -> None:
        await self.run('CREATE INDEX kg_entity_build IF NOT EXISTS FOR (e:KGEntity) ON (e.build_id, e.id)')
        await self.run('CREATE INDEX kg_community_build IF NOT EXISTS FOR (c:KGCommunity) ON (c.build_id, c.id)')
        from .norm import norm_name
        for start in range(0, len(graph.entities), BATCH):
            await self.run(
                'UNWIND $rows AS row CREATE (e:KGEntity {id: row.id, build_id: $build, kb_id: $kb, name: row.name, '
                'norm: row.norm, type: row.type, description: row.description, sources: row.sources, degree: row.degree})',
                build=build_id, kb=kb_id, rows=[{
                    'id': e.id, 'name': e.name, 'norm': norm_name(e.name), 'type': e.type, 'description': e.description,
                    'sources': _dump(e.sources), 'degree': e.degree} for e in graph.entities[start:start + BATCH]])
        for start in range(0, len(graph.relations), BATCH):
            await self.run(
                'UNWIND $rows AS row MATCH (a:KGEntity {build_id: $build, id: row.source}) '
                'MATCH (b:KGEntity {build_id: $build, id: row.target}) '
                'CREATE (a)-[:KG_REL {id: row.id, build_id: $build, kb_id: $kb, description: row.description, '
                'keywords: row.keywords, weight: row.weight, sources: row.sources}]->(b)',
                build=build_id, kb=kb_id, rows=[{
                    'id': r.id, 'source': r.source_id, 'target': r.target_id, 'description': r.description,
                    'keywords': list(r.keywords), 'weight': r.weight, 'sources': _dump(r.sources)}
                    for r in graph.relations[start:start + BATCH]])
        for start in range(0, len(graph.communities), BATCH):
            await self.run(
                'UNWIND $rows AS row CREATE (c:KGCommunity {id: row.id, build_id: $build, kb_id: $kb, level: row.level, '
                'entity_ids: row.entity_ids, title: row.title, summary: row.summary, sources: row.sources})',
                build=build_id, kb=kb_id, rows=[{
                    'id': c.id, 'level': c.level, 'entity_ids': list(c.entity_ids), 'title': c.title,
                    'summary': c.summary, 'sources': _dump(c.sources)} for c in graph.communities[start:start + BATCH]])

    async def delete(self, build_id: str) -> None:
        await self.run('MATCH (n) WHERE n.build_id = $build DETACH DELETE n', build=build_id)

    @staticmethod
    def _entity(row: dict[str, Any]) -> EntityOut:
        return EntityOut(row['id'], row['name'], row['type'], row['description'], _sources(row['sources']),
                         int(row['degree'] or 0))

    @staticmethod
    def _relation(row: dict[str, Any]) -> RelationOut:
        return RelationOut(row['id'], row['source'], row['target'], row['description'], tuple(row['keywords'] or ()),
                           float(row['weight'] or 1), _sources(row['sources']))

    async def entities(self, build_id: str, ids: list[str]) -> list[EntityOut]:
        if not ids:
            return []
        rows = await self.run('MATCH (e:KGEntity {build_id: $build}) WHERE e.id IN $ids RETURN e.id AS id, e.name AS name, '
                              'e.type AS type, e.description AS description, e.sources AS sources, e.degree AS degree',
                              build=build_id, ids=ids)
        by_id = {row['id']: self._entity(row) for row in rows}
        return [by_id[i] for i in ids if i in by_id]

    async def match_names(self, build_id: str, norms: list[str], limit: int) -> list[EntityOut]:
        if not norms:
            return []
        rows = await self.run('MATCH (e:KGEntity {build_id: $build}) WHERE e.norm IN $norms RETURN e.id AS id, '
                              'e.name AS name, e.type AS type, e.description AS description, e.sources AS sources, '
                              'e.degree AS degree ORDER BY e.degree DESC, e.id LIMIT $limit',
                              build=build_id, norms=norms, limit=limit)
        return [self._entity(row) for row in rows]

    async def edges(self, build_id: str, entity_ids: list[str]) -> list[RelationOut]:
        if not entity_ids:
            return []
        rows = await self.run('MATCH (a:KGEntity {build_id: $build})-[r:KG_REL {build_id: $build}]->(b:KGEntity) '
                              'WHERE a.id IN $ids OR b.id IN $ids RETURN r.id AS id, a.id AS source, b.id AS target, '
                              'r.description AS description, r.keywords AS keywords, r.weight AS weight, '
                              'r.sources AS sources', build=build_id, ids=entity_ids)
        return [self._relation(row) for row in rows]

    async def relations(self, build_id: str, ids: list[str]) -> list[RelationOut]:
        if not ids:
            return []
        rows = await self.run('MATCH (a:KGEntity {build_id: $build})-[r:KG_REL {build_id: $build}]->(b:KGEntity) '
                              'WHERE r.id IN $ids RETURN r.id AS id, a.id AS source, b.id AS target, '
                              'r.description AS description, r.keywords AS keywords, r.weight AS weight, '
                              'r.sources AS sources', build=build_id, ids=ids)
        by_id = {row['id']: self._relation(row) for row in rows}
        return [by_id[i] for i in ids if i in by_id]

    async def communities(self, build_id: str, ids: list[str]) -> list[CommunityOut]:
        if not ids:
            return []
        rows = await self.run('MATCH (c:KGCommunity {build_id: $build}) WHERE c.id IN $ids RETURN c.id AS id, '
                              'c.level AS level, c.entity_ids AS entity_ids, c.title AS title, c.summary AS summary, '
                              'c.sources AS sources', build=build_id, ids=ids)
        by_id = {row['id']: CommunityOut(row['id'], int(row['level'] or 0), tuple(row['entity_ids'] or ()), row['title'],
                                         row['summary'], _sources(row['sources'])) for row in rows}
        return [by_id[i] for i in ids if i in by_id]

    async def community_ids_of(self, build_id: str, entity_ids: list[str], limit: int) -> list[str]:
        rows = await self.run('MATCH (c:KGCommunity {build_id: $build}) RETURN c.id AS id, c.entity_ids AS entity_ids',
                              build=build_id)
        wanted = set(entity_ids)
        scored = [(len(wanted & set(row['entity_ids'] or ())), row['id']) for row in rows]
        scored = [item for item in scored if item[0] > 0]
        scored.sort(key=lambda item: (-item[0], item[1]))
        return [cid for _, cid in scored[:limit]]


capabilities.mark_available('graph_store', 'neo4j', verified=False)
