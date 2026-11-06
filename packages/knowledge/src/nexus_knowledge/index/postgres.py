"""PostgreSQL pgvector engine (K1, implemented, not yet verified against a real database).

One table per collection: ``chunk_id`` (primary key), ``kb_id``, ``version_id``, ``tokens``,
``tsv tsvector`` (generated from the tokens with the ``simple`` configuration, decision 2: the same CJK
bigram tokens as every other engine, no Chinese segmenter extension), ``dim`` and ``embedding vector``.
The embedding column has no fixed size, so one table can hold several models; vector search casts to the
query's dimension and filters ``dim``, and ``upsert`` creates a partial HNSW index per dimension
(``(embedding::vector(D)) vector_cosine_ops WHERE dim = D``).

Pre-Filter: both searches carry ``version_id = ANY(%s)`` in the statement. The ``vector`` extension must
exist (``CREATE EXTENSION vector`` is an operator step, as in Octop ``pg_index.py``); otherwise ``ping`` and
every call raise ``pgvector_missing`` with the fix.

``connection_config``: ``{"dsn": "postgresql://user:pass@host:5432/db"}``.
"""
from __future__ import annotations

import re
from typing import Any, Mapping, Sequence

from ..retrieval.fuse import Candidate
from .base import IndexRow, Scope, VectorIndex, VectorStoreError, register_engine

_NAME = re.compile(r'^[a-z][a-z0-9_]{0,62}$')


def _literal(vector: Sequence[float]) -> str:
    return '[' + ','.join(format(float(value), '.8g') for value in vector) + ']'


class PostgresVectorIndex(VectorIndex):
    engine = 'postgres'

    def __init__(self, connection: Mapping[str, Any], index: Mapping[str, Any] | None = None) -> None:
        self.dsn = str(connection.get('dsn') or '').strip()
        if not self.dsn:
            raise VectorStoreError('invalid_config', 'postgres vector store needs a dsn')
        self.schema = str((index or {}).get('schema') or 'public')
        if not _NAME.match(self.schema):
            raise VectorStoreError('invalid_config', 'invalid schema name')
        self._ready: set[str] = set()
        self._indexed: set[tuple[str, int]] = set()

    async def _connect(self):
        import psycopg

        try:
            return await psycopg.AsyncConnection.connect(self.dsn, autocommit=False)
        except psycopg.Error as exc:
            raise VectorStoreError('connection_failed', type(exc).__name__) from exc

    def _table(self, collection: str) -> str:
        if not _NAME.match(collection):
            raise VectorStoreError('invalid_collection', f'invalid collection name: {collection}')
        return f'{self.schema}.{collection}'

    @staticmethod
    async def _require_extension(conn) -> None:
        row = await (await conn.execute("SELECT 1 FROM pg_type WHERE typname = 'vector'")).fetchone()
        if row is None:
            raise VectorStoreError('pgvector_missing',
                                   'pgvector is not installed: run CREATE EXTENSION vector on this database')

    async def _ensure(self, conn, table: str) -> None:
        if table in self._ready:
            return
        await self._require_extension(conn)
        await conn.execute(
            f'CREATE TABLE IF NOT EXISTS {table} (chunk_id TEXT PRIMARY KEY, kb_id TEXT NOT NULL, '
            'version_id TEXT NOT NULL, tokens TEXT NOT NULL DEFAULT \'\', '
            "tsv tsvector GENERATED ALWAYS AS (to_tsvector('simple', tokens)) STORED, dim INTEGER, embedding vector)")
        base = table.split('.')[-1]
        await conn.execute(f'CREATE INDEX IF NOT EXISTS {base}_version ON {table} (version_id)')
        await conn.execute(f'CREATE INDEX IF NOT EXISTS {base}_tsv ON {table} USING gin (tsv)')
        self._ready.add(table)

    async def _ensure_hnsw(self, conn, table: str, dimension: int) -> None:
        if (table, dimension) in self._indexed:
            return
        base = table.split('.')[-1]
        await conn.execute(
            f'CREATE INDEX IF NOT EXISTS {base}_hnsw_{dimension} ON {table} USING hnsw '
            f'((embedding::vector({dimension})) vector_cosine_ops) WHERE dim = {dimension}')
        self._indexed.add((table, dimension))

    async def ping(self) -> dict[str, Any]:
        conn = await self._connect()
        async with conn:
            version = (await (await conn.execute('SHOW server_version')).fetchone())[0]
            await self._require_extension(conn)
            ext = await (await conn.execute("SELECT extversion FROM pg_extension WHERE extname='vector'")).fetchone()
        return {'engine': 'postgres', 'version': version, 'pgvector': ext[0] if ext else None}

    async def upsert(self, collection: str, rows: Sequence[IndexRow], *, dimension: int | None) -> None:
        table = self._table(collection)
        conn = await self._connect()
        async with conn:
            await self._ensure(conn, table)
            if dimension:
                await self._ensure_hnsw(conn, table, int(dimension))
            async with conn.cursor() as cur:
                await cur.executemany(
                    f'INSERT INTO {table} (chunk_id, kb_id, version_id, tokens, dim, embedding) '
                    'VALUES (%s, %s, %s, %s, %s, %s::vector) ON CONFLICT (chunk_id) DO UPDATE SET '
                    'kb_id = EXCLUDED.kb_id, version_id = EXCLUDED.version_id, tokens = EXCLUDED.tokens, '
                    'dim = EXCLUDED.dim, embedding = EXCLUDED.embedding',
                    [(row.chunk_id, row.kb_id, row.version_id, row.tokens,
                      len(row.vector) if row.vector is not None else None,
                      _literal(row.vector) if row.vector is not None else None) for row in rows])
            await conn.commit()

    async def delete_versions(self, collection: str, version_ids: Sequence[str]) -> None:
        table = self._table(collection)
        conn = await self._connect()
        async with conn:
            if await self._exists(conn, table):
                await conn.execute(f'DELETE FROM {table} WHERE version_id = ANY(%s)', (list(version_ids),))
                await conn.commit()

    async def drop_collection(self, collection: str) -> None:
        table = self._table(collection)
        conn = await self._connect()
        async with conn:
            await conn.execute(f'DROP TABLE IF EXISTS {table}')
            await conn.commit()
        self._ready.discard(table)

    async def _exists(self, conn, table: str) -> bool:
        row = await (await conn.execute('SELECT to_regclass(%s)', (table,))).fetchone()
        return bool(row and row[0])

    async def search_vector(self, collection: str, query: Sequence[float], scope: Scope, k: int) -> list[Candidate]:
        if not scope.version_ids or k <= 0:
            return []
        table, dim, literal = self._table(collection), len(query), _literal(query)
        conn = await self._connect()
        async with conn:
            if not await self._exists(conn, table):
                return []
            rows = await (await conn.execute(
                f'SELECT chunk_id, 1 - (embedding::vector({dim}) <=> %s::vector({dim})) AS score FROM {table} '
                f'WHERE dim = {dim} AND version_id = ANY(%s) '
                f'ORDER BY embedding::vector({dim}) <=> %s::vector({dim}) LIMIT %s',
                (literal, list(scope.version_ids), literal, k))).fetchall()
        return [Candidate(chunk_id, max(0.0, min(1.0, float(score)))) for chunk_id, score in rows]

    async def search_keyword(self, collection: str, tokens: Sequence[str], scope: Scope, k: int) -> list[Candidate]:
        if not tokens or not scope.version_ids or k <= 0:
            return []
        table = self._table(collection)
        # Tokens contain only letters, digits, underscore and CJK; quoting keeps tsquery syntax inert anyway.
        query = ' | '.join("'" + token.replace("'", '') + "'" for token in tokens if token)
        conn = await self._connect()
        async with conn:
            if not await self._exists(conn, table):
                return []
            rows = await (await conn.execute(
                f"SELECT chunk_id, ts_rank(tsv, to_tsquery('simple', %s)) AS score FROM {table} "
                f"WHERE tsv @@ to_tsquery('simple', %s) AND version_id = ANY(%s) ORDER BY score DESC LIMIT %s",
                (query, query, list(scope.version_ids), k))).fetchall()
        return [Candidate(chunk_id, float(score)) for chunk_id, score in rows if score > 0]


register_engine('postgres', PostgresVectorIndex, verified=False)
