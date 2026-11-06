"""Qdrant engine (K1, implemented, not yet verified against a real Qdrant).

REST API (``/collections``). One collection per knowledge base, named ``<collection_prefix><collection>``,
cosine distance, payload ``chunk_id``, ``kb_id``, ``version_id``, ``tokens`` with keyword indexes on
``version_id`` and a whitespace full-text index on ``tokens``. Point ids are the chunk UUIDs.

Pre-Filter: every query carries ``must: version_id in scope`` as a Qdrant filter.

Keyword channel: Qdrant's full-text match filters but does not rank, so candidates are fetched with
``should`` text matches inside the scope and ranked here by the number of distinct query tokens they
contain (a coarse score; RRF uses only the rank). Vectors are required: a knowledge base on Qdrant must have
an embedding model (``requires_vectors``).

``connection_config``: ``{"url": "http://host:6333", "api_key": "...", "verify_tls": true}``;
``index_config``: ``{"collection_prefix": "nexus_", "shard_number": 1, "replication_factor": 1}``.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from ..retrieval.fuse import Candidate
from ._http import RestClient
from .base import IndexRow, Scope, VectorIndex, VectorStoreError, register_engine

_KEYWORD_FETCH_FACTOR = 5


class QdrantVectorIndex(VectorIndex):
    engine = 'qdrant'
    requires_vectors = True

    def __init__(self, connection: Mapping[str, Any], index: Mapping[str, Any] | None = None) -> None:
        index = index or {}
        headers = {'api-key': str(connection['api_key'])} if connection.get('api_key') else {}
        self.client = RestClient(str(connection.get('url') or ''), headers,
                                 verify_tls=bool(connection.get('verify_tls', True)))
        self.prefix = str(index.get('collection_prefix') or 'nexus_')
        self.shards = int(index.get('shard_number') or 1)
        self.replicas = int(index.get('replication_factor') or 1)
        self._ready: set[str] = set()

    def _name(self, collection: str) -> str:
        return self.prefix + collection

    async def ping(self) -> dict[str, Any]:
        info = await self.client.request('GET', '/')
        return {'engine': 'qdrant', 'version': (info or {}).get('version')}

    async def _ensure(self, name: str, dimension: int) -> None:
        if name in self._ready:
            return
        existing = await self.client.request('GET', f'/collections/{name}', allow=(404,))
        if existing is None:
            await self.client.request('PUT', f'/collections/{name}', {
                'vectors': {'size': dimension, 'distance': 'Cosine'},
                'shard_number': self.shards, 'replication_factor': self.replicas})
            for field, schema in (('version_id', 'keyword'), ('kb_id', 'keyword'),
                                  ('tokens', {'type': 'text', 'tokenizer': 'whitespace', 'lowercase': True})):
                await self.client.request('PUT', f'/collections/{name}/index?wait=true',
                                          {'field_name': field, 'field_schema': schema})
        else:
            size = (((existing.get('result') or {}).get('config') or {}).get('params') or {}).get('vectors', {})
            if isinstance(size, dict) and size.get('size') not in (None, dimension):
                raise VectorStoreError('dimension_mismatch',
                                       f'collection {name} has size {size.get("size")}, not {dimension}')
        self._ready.add(name)

    async def upsert(self, collection: str, rows: Sequence[IndexRow], *, dimension: int | None) -> None:
        if not rows:
            return
        if not dimension or any(row.vector is None for row in rows):
            raise VectorStoreError('vector_required', 'Qdrant stores need an embedding model')
        name = self._name(collection)
        await self._ensure(name, int(dimension))
        points = [{'id': row.chunk_id, 'vector': [float(x) for x in row.vector],
                   'payload': {'chunk_id': row.chunk_id, 'kb_id': row.kb_id, 'version_id': row.version_id,
                               'tokens': row.tokens}} for row in rows]
        await self.client.request('PUT', f'/collections/{name}/points?wait=true', {'points': points})

    async def delete_versions(self, collection: str, version_ids: Sequence[str]) -> None:
        name = self._name(collection)
        await self.client.request('POST', f'/collections/{name}/points/delete?wait=true', {
            'filter': {'must': [{'key': 'version_id', 'match': {'any': list(version_ids)}}]}}, allow=(404,))

    async def drop_collection(self, collection: str) -> None:
        name = self._name(collection)
        await self.client.request('DELETE', f'/collections/{name}', allow=(404,))
        self._ready.discard(name)

    @staticmethod
    def _scope_filter(scope: Scope) -> dict[str, Any]:
        return {'key': 'version_id', 'match': {'any': list(scope.version_ids)}}

    async def search_vector(self, collection: str, query: Sequence[float], scope: Scope, k: int) -> list[Candidate]:
        if not scope.version_ids or k <= 0:
            return []
        result = await self.client.request('POST', f'/collections/{self._name(collection)}/points/query', {
            'query': [float(x) for x in query], 'limit': k, 'with_payload': ['chunk_id'],
            'filter': {'must': [self._scope_filter(scope)]}}, allow=(404,))
        points = ((result or {}).get('result') or {}).get('points', [])
        return [Candidate(str(p['payload']['chunk_id']), max(0.0, min(1.0, float(p['score'])))) for p in points]

    async def search_keyword(self, collection: str, tokens: Sequence[str], scope: Scope, k: int) -> list[Candidate]:
        if not tokens or not scope.version_ids or k <= 0:
            return []
        result = await self.client.request('POST', f'/collections/{self._name(collection)}/points/scroll', {
            'limit': k * _KEYWORD_FETCH_FACTOR, 'with_payload': ['chunk_id', 'tokens'], 'with_vector': False,
            'filter': {'must': [self._scope_filter(scope)],
                       'should': [{'key': 'tokens', 'match': {'text': token}} for token in tokens]}},
            allow=(404,))
        points = ((result or {}).get('result') or {}).get('points', [])
        wanted = set(tokens)
        scored = []
        for point in points:
            have = set(str(point['payload'].get('tokens', '')).split())
            hits = len(wanted & have)
            if hits:
                scored.append(Candidate(str(point['payload']['chunk_id']), float(hits)))
        scored.sort(key=lambda c: (-c.score, c.chunk_id))
        return scored[:k]

    async def close(self) -> None:
        await self.client.close()


register_engine('qdrant', QdrantVectorIndex, verified=False)
