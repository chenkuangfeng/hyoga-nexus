"""Milvus engine (K1, implemented, not yet verified against a real Milvus). Requires Milvus 2.5+ (REST v2).

One collection per knowledge base, named ``<collection_prefix><collection>``, created on the first upsert:

- ``chunk_id`` VarChar primary key, ``kb_id`` and ``version_id`` VarChar (``version_id`` has an inverted
  index for filtering);
- ``tokens`` VarChar with ``enable_analyzer`` and a whitespace tokenizer, feeding a ``BM25`` function that
  fills the ``sparse`` SparseFloatVector field (Milvus full-text search) for the keyword channel;
- ``embedding`` FloatVector with an ``AUTOINDEX`` / ``COSINE`` index.

Pre-Filter: both searches pass ``filter: version_id in [...]`` to ``/v2/vectordb/entities/search``; ids are
validated as UUID-like strings before they enter the expression. Vectors are required
(``requires_vectors``).

``connection_config``: ``{"url": "http://host:19530", "token": "user:password or API key",
"database": "default", "verify_tls": true}``; ``index_config``: ``{"collection_prefix": "nexus_",
"shards_num": 1}``.
"""
from __future__ import annotations

import re
from typing import Any, Mapping, Sequence

from ..retrieval.fuse import Candidate
from ._http import RestClient
from .base import IndexRow, Scope, VectorIndex, VectorStoreError, register_engine

_SAFE_ID = re.compile(r'^[A-Za-z0-9_-]{1,64}$')
_TOKENS_MAX = 65535


def _in_list(field: str, values: Sequence[str]) -> str:
    for value in values:
        if not _SAFE_ID.match(value):
            raise VectorStoreError('invalid_scope', 'scope ids must be plain identifiers')
    return f'{field} in [' + ','.join(f'"{value}"' for value in values) + ']'


class MilvusVectorIndex(VectorIndex):
    engine = 'milvus'
    requires_vectors = True

    def __init__(self, connection: Mapping[str, Any], index: Mapping[str, Any] | None = None) -> None:
        index = index or {}
        headers = {'Content-Type': 'application/json'}
        if connection.get('token'):
            headers['Authorization'] = f'Bearer {connection["token"]}'
        self.client = RestClient(str(connection.get('url') or ''), headers,
                                 verify_tls=bool(connection.get('verify_tls', True)))
        self.database = str(connection.get('database') or 'default')
        self.prefix = str(index.get('collection_prefix') or 'nexus_')
        self.shards = int(index.get('shards_num') or 1)
        self._ready: set[str] = set()

    def _name(self, collection: str) -> str:
        return self.prefix + collection

    async def _call(self, path: str, body: dict[str, Any]) -> Any:
        result = await self.client.request('POST', path, {'dbName': self.database, **body})
        if isinstance(result, dict) and result.get('code') not in (0, 200, None):
            raise VectorStoreError(f'milvus_{result.get("code")}', str(result.get('message'))[:300])
        return (result or {}).get('data') if isinstance(result, dict) else None

    async def ping(self) -> dict[str, Any]:
        data = await self._call('/v2/vectordb/collections/list', {})
        return {'engine': 'milvus', 'database': self.database, 'collections': len(data or [])}

    async def _exists(self, name: str) -> bool:
        data = await self._call('/v2/vectordb/collections/has', {'collectionName': name})
        return bool((data or {}).get('has'))

    async def _ensure(self, name: str, dimension: int) -> None:
        if name in self._ready:
            return
        if not await self._exists(name):
            await self._call('/v2/vectordb/collections/create', {
                'collectionName': name,
                'schema': {
                    'autoId': False, 'enableDynamicField': False,
                    'fields': [
                        {'fieldName': 'chunk_id', 'dataType': 'VarChar', 'isPrimary': True,
                         'elementTypeParams': {'max_length': 64}},
                        {'fieldName': 'kb_id', 'dataType': 'VarChar', 'elementTypeParams': {'max_length': 64}},
                        {'fieldName': 'version_id', 'dataType': 'VarChar', 'elementTypeParams': {'max_length': 64}},
                        {'fieldName': 'tokens', 'dataType': 'VarChar',
                         'elementTypeParams': {'max_length': _TOKENS_MAX, 'enable_analyzer': True,
                                               'analyzer_params': {'tokenizer': 'whitespace'}}},
                        {'fieldName': 'sparse', 'dataType': 'SparseFloatVector'},
                        {'fieldName': 'embedding', 'dataType': 'FloatVector',
                         'elementTypeParams': {'dim': dimension}},
                    ],
                    'functions': [{'name': 'tokens_bm25', 'type': 'BM25', 'inputFieldNames': ['tokens'],
                                   'outputFieldNames': ['sparse'], 'params': {}}],
                },
                'indexParams': [
                    {'fieldName': 'embedding', 'indexName': 'embedding', 'metricType': 'COSINE',
                     'indexType': 'AUTOINDEX'},
                    {'fieldName': 'sparse', 'indexName': 'sparse', 'metricType': 'BM25',
                     'indexType': 'SPARSE_INVERTED_INDEX'},
                    {'fieldName': 'version_id', 'indexName': 'version_id', 'indexType': 'INVERTED'},
                ],
                'params': {'shardsNum': self.shards},
            })
        await self._call('/v2/vectordb/collections/load', {'collectionName': name})
        self._ready.add(name)

    async def upsert(self, collection: str, rows: Sequence[IndexRow], *, dimension: int | None) -> None:
        if not rows:
            return
        if not dimension or any(row.vector is None for row in rows):
            raise VectorStoreError('vector_required', 'Milvus stores need an embedding model')
        name = self._name(collection)
        await self._ensure(name, int(dimension))
        await self._call('/v2/vectordb/entities/upsert', {'collectionName': name, 'data': [
            {'chunk_id': row.chunk_id, 'kb_id': row.kb_id, 'version_id': row.version_id,
             'tokens': row.tokens[:_TOKENS_MAX], 'embedding': [float(x) for x in row.vector]} for row in rows]})

    async def delete_versions(self, collection: str, version_ids: Sequence[str]) -> None:
        name = self._name(collection)
        if version_ids and await self._exists(name):
            await self._call('/v2/vectordb/entities/delete',
                             {'collectionName': name, 'filter': _in_list('version_id', version_ids)})

    async def drop_collection(self, collection: str) -> None:
        name = self._name(collection)
        if await self._exists(name):
            await self._call('/v2/vectordb/collections/drop', {'collectionName': name})
        self._ready.discard(name)

    async def _search(self, collection: str, field: str, data: Any, scope: Scope, k: int) -> list[dict[str, Any]]:
        name = self._name(collection)
        if not await self._exists(name):
            return []
        result = await self._call('/v2/vectordb/entities/search', {
            'collectionName': name, 'annsField': field, 'data': [data], 'limit': k,
            'filter': _in_list('version_id', scope.version_ids), 'outputFields': ['chunk_id']})
        return list(result or [])

    async def search_vector(self, collection: str, query: Sequence[float], scope: Scope, k: int) -> list[Candidate]:
        if not scope.version_ids or k <= 0:
            return []
        hits = await self._search(collection, 'embedding', [float(x) for x in query], scope, k)
        return [Candidate(str(hit['chunk_id']), max(0.0, min(1.0, float(hit.get('distance', 0))))) for hit in hits]

    async def search_keyword(self, collection: str, tokens: Sequence[str], scope: Scope, k: int) -> list[Candidate]:
        if not tokens or not scope.version_ids or k <= 0:
            return []
        hits = await self._search(collection, 'sparse', ' '.join(tokens), scope, k)
        return [Candidate(str(hit['chunk_id']), float(hit.get('distance', 0))) for hit in hits
                if float(hit.get('distance', 0)) > 0]

    async def close(self) -> None:
        await self.client.close()


register_engine('milvus', MilvusVectorIndex, verified=False)
