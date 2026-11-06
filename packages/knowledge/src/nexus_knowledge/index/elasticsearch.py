"""Elasticsearch engine (K1, implemented, not yet verified against a real cluster). Requires ES 8.x.

One index per knowledge base, named ``<index_prefix><collection>``. Mapping: ``chunk_id``, ``kb_id``,
``version_id`` as ``keyword``; ``tokens`` as ``text`` with the ``whitespace`` analyzer (the tokens are already
CJK bigrams and lowercase words, so ES scores them with BM25 exactly as given); ``embedding`` as
``dense_vector`` with cosine similarity, added on the first upsert that carries vectors.

Pre-Filter: kNN search passes ``filter: terms version_id`` (applied during the approximate search, not after),
and keyword search puts the same ``terms`` in ``bool.filter``.

ES reports cosine kNN scores as ``(1 + cos) / 2``; they are converted back to cosine.

``connection_config``: ``{"url": "https://host:9200", "username": "...", "password": "...",
"api_key": "...", "verify_tls": true}``; ``index_config``: ``{"index_prefix": "nexus_",
"number_of_shards": 1, "number_of_replicas": 1}``.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from ..retrieval.fuse import Candidate
from ._http import RestClient
from .base import IndexRow, Scope, VectorIndex, VectorStoreError, register_engine

_NUM_CANDIDATES_FACTOR = 10


class ElasticsearchVectorIndex(VectorIndex):
    engine = 'elasticsearch'

    def __init__(self, connection: Mapping[str, Any], index: Mapping[str, Any] | None = None) -> None:
        index = index or {}
        headers = {'Content-Type': 'application/json'}
        if connection.get('api_key'):
            headers['Authorization'] = f'ApiKey {connection["api_key"]}'
        auth = None
        if connection.get('username'):
            auth = (str(connection['username']), str(connection.get('password') or ''))
        self.client = RestClient(str(connection.get('url') or ''), headers, auth=auth,
                                 verify_tls=bool(connection.get('verify_tls', True)))
        self.prefix = str(index.get('index_prefix') or 'nexus_')
        self.shards = int(index.get('number_of_shards') or 1)
        self.replicas = int(index.get('number_of_replicas') or 1)
        self._ready: dict[str, int | None] = {}

    def _name(self, collection: str) -> str:
        return self.prefix + collection

    async def ping(self) -> dict[str, Any]:
        info = await self.client.request('GET', '/')
        return {'engine': 'elasticsearch', 'version': ((info or {}).get('version') or {}).get('number')}

    async def _ensure(self, name: str, dimension: int | None) -> None:
        if name in self._ready and (dimension is None or self._ready[name] == dimension):
            return
        current = await self.client.request('GET', f'/{name}/_mapping', allow=(404,))
        if current is None:
            properties: dict[str, Any] = {
                'chunk_id': {'type': 'keyword'}, 'kb_id': {'type': 'keyword'}, 'version_id': {'type': 'keyword'},
                'tokens': {'type': 'text', 'analyzer': 'whitespace'}}
            if dimension:
                properties['embedding'] = {'type': 'dense_vector', 'dims': dimension, 'index': True,
                                           'similarity': 'cosine'}
            await self.client.request('PUT', f'/{name}', {
                'settings': {'number_of_shards': self.shards, 'number_of_replicas': self.replicas},
                'mappings': {'properties': properties}})
            self._ready[name] = dimension
            return
        props = (((current.get(name) or {}).get('mappings') or {}).get('properties') or {})
        existing = (props.get('embedding') or {}).get('dims')
        if dimension and existing is None:
            await self.client.request('PUT', f'/{name}/_mapping', {'properties': {'embedding': {
                'type': 'dense_vector', 'dims': dimension, 'index': True, 'similarity': 'cosine'}}})
            existing = dimension
        if dimension and existing != dimension:
            raise VectorStoreError('dimension_mismatch', f'index {name} has dims {existing}, not {dimension}')
        self._ready[name] = existing

    async def upsert(self, collection: str, rows: Sequence[IndexRow], *, dimension: int | None) -> None:
        if not rows:
            return
        name = self._name(collection)
        await self._ensure(name, dimension)
        lines = []
        import json

        for row in rows:
            doc: dict[str, Any] = {'chunk_id': row.chunk_id, 'kb_id': row.kb_id, 'version_id': row.version_id,
                                   'tokens': row.tokens}
            if row.vector is not None:
                doc['embedding'] = [float(x) for x in row.vector]
            lines.append(json.dumps({'index': {'_index': name, '_id': row.chunk_id}}))
            lines.append(json.dumps(doc, ensure_ascii=False))
        response = await self._bulk('\n'.join(lines) + '\n')
        if (response or {}).get('errors'):
            first = next((item for item in response.get('items', []) if item.get('index', {}).get('error')), {})
            raise VectorStoreError('bulk_failed', str(first.get('index', {}).get('error'))[:300])

    async def _bulk(self, body: str) -> Any:
        import httpx

        try:
            response = await self.client._client.post('/_bulk?refresh=wait_for', content=body.encode(),
                                                      headers={'Content-Type': 'application/x-ndjson'})
        except httpx.HTTPError as exc:
            raise VectorStoreError('connection_failed', f'POST /_bulk: {type(exc).__name__}') from exc
        if response.status_code >= 400:
            raise VectorStoreError(f'http_{response.status_code}', response.text[:300])
        return response.json()

    async def delete_versions(self, collection: str, version_ids: Sequence[str]) -> None:
        await self.client.request('POST', f'/{self._name(collection)}/_delete_by_query?refresh=true', {
            'query': {'terms': {'version_id': list(version_ids)}}}, allow=(404,))

    async def drop_collection(self, collection: str) -> None:
        name = self._name(collection)
        await self.client.request('DELETE', f'/{name}', allow=(404,))
        self._ready.pop(name, None)

    async def search_vector(self, collection: str, query: Sequence[float], scope: Scope, k: int) -> list[Candidate]:
        if not scope.version_ids or k <= 0:
            return []
        result = await self.client.request('POST', f'/{self._name(collection)}/_search', {
            'size': k, '_source': ['chunk_id'],
            'knn': {'field': 'embedding', 'query_vector': [float(x) for x in query], 'k': k,
                    'num_candidates': max(k * _NUM_CANDIDATES_FACTOR, 50),
                    'filter': {'terms': {'version_id': list(scope.version_ids)}}}}, allow=(404,))
        hits = ((result or {}).get('hits') or {}).get('hits', [])
        return [Candidate(str(hit['_source']['chunk_id']), max(0.0, min(1.0, 2 * float(hit['_score']) - 1)))
                for hit in hits]

    async def search_keyword(self, collection: str, tokens: Sequence[str], scope: Scope, k: int) -> list[Candidate]:
        if not tokens or not scope.version_ids or k <= 0:
            return []
        result = await self.client.request('POST', f'/{self._name(collection)}/_search', {
            'size': k, '_source': ['chunk_id'],
            'query': {'bool': {'must': {'match': {'tokens': {'query': ' '.join(tokens), 'operator': 'or'}}},
                               'filter': {'terms': {'version_id': list(scope.version_ids)}}}}}, allow=(404,))
        hits = ((result or {}).get('hits') or {}).get('hits', [])
        return [Candidate(str(hit['_source']['chunk_id']), float(hit['_score'])) for hit in hits]

    async def close(self) -> None:
        await self.client.close()


register_engine('elasticsearch', ElasticsearchVectorIndex, verified=False)
