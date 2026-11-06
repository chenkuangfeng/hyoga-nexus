"""SQLite vector engine (K1, tested): one database file, FTS5 keyword index and in-process cosine.

For local development and small libraries (decision 1). Layout, one pair of tables per collection:

- ``<collection>``: ``rowid``, ``chunk_id`` (unique), ``version_id``, ``dim``, ``norm``, ``vector``
  (float32 bytes, NULL for keyword-only rows);
- ``<collection>_fts``: contentless FTS5 over the tokens, ``rowid`` shared with the row table
  (WeKnora ``retriever/sqlite``; same contentless pattern as ``memory_fts``).

Both searches restrict candidates with ``version_id IN (SELECT value FROM json_each(?))`` inside the SQL
statement (Pre-Filter pushed down). Vector search reads only the in-scope vectors of the query's dimension
and ranks them in Python; cost grows with the size of the scope, which is fine for development libraries.
A driver without FTS5 (or SQLite < 3.43, no ``contentless_delete``) disables the keyword channel instead
of failing.

The file is opened per call (``check_same_thread`` is irrelevant) and work runs in a thread so the event
loop never blocks. ``connection_config``: ``{"path": "data/knowledge/vectors.db"}``; ``":memory:"`` is not
supported because each call opens a new connection.
"""
from __future__ import annotations

import asyncio
import json
import math
import re
import sqlite3
from array import array
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..retrieval.fuse import Candidate
from .base import IndexRow, Scope, VectorIndex, VectorStoreError, register_engine

_NAME = re.compile(r'^[a-z][a-z0-9_]{0,62}$')
_FTS_MIN = (3, 43, 0)


def _pack(vector: Sequence[float]) -> tuple[bytes, float]:
    values = array('f', (float(x) for x in vector))
    return values.tobytes(), math.sqrt(sum(x * x for x in values))


def _unpack(blob: bytes) -> array:
    values = array('f')
    values.frombytes(blob)
    return values


class SqliteVectorIndex(VectorIndex):
    engine = 'sqlite'

    def __init__(self, connection: Mapping[str, Any], index: Mapping[str, Any] | None = None) -> None:
        path = str(connection.get('path') or '').strip()
        if not path or path == ':memory:':
            raise VectorStoreError('invalid_config', 'sqlite vector store needs a file path')
        self.path = Path(path)
        self.supports_keyword = sqlite3.sqlite_version_info >= _FTS_MIN and self._probe_fts()

    @staticmethod
    def _probe_fts() -> bool:
        try:
            with sqlite3.connect(':memory:') as db:
                db.execute("CREATE VIRTUAL TABLE t USING fts5(x, content='', contentless_delete=1)")
            return True
        except sqlite3.Error:
            return False

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=30)
        db.execute('PRAGMA journal_mode=WAL')
        return db

    @staticmethod
    def _table(collection: str) -> str:
        if not _NAME.match(collection):
            raise VectorStoreError('invalid_collection', f'invalid collection name: {collection}')
        return collection

    def _ensure(self, db: sqlite3.Connection, table: str) -> None:
        db.execute(f'CREATE TABLE IF NOT EXISTS {table} (rowid INTEGER PRIMARY KEY, chunk_id TEXT NOT NULL UNIQUE, '
                   'kb_id TEXT NOT NULL, version_id TEXT NOT NULL, dim INTEGER, norm REAL, vector BLOB)')
        db.execute(f'CREATE INDEX IF NOT EXISTS {table}_version ON {table}(version_id)')
        if self.supports_keyword:
            db.execute(f"CREATE VIRTUAL TABLE IF NOT EXISTS {table}_fts USING fts5(tokens, content='', "
                       'contentless_delete=1)')

    async def _run(self, fn, *args):
        try:
            return await asyncio.to_thread(fn, *args)
        except sqlite3.Error as exc:
            raise VectorStoreError('sqlite_error', str(exc)) from exc

    async def ping(self) -> dict[str, Any]:
        def work():
            with self._connect() as db:
                db.execute('SELECT 1')
            return {'engine': 'sqlite', 'version': sqlite3.sqlite_version, 'keyword': self.supports_keyword,
                    'path': str(self.path)}
        return await self._run(work)

    def _exists(self, db: sqlite3.Connection, table: str) -> bool:
        return db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone() is not None

    def _delete_rowids(self, db: sqlite3.Connection, table: str, rowids: list[int]) -> None:
        for rowid in rowids:
            if self.supports_keyword:
                db.execute(f'DELETE FROM {table}_fts WHERE rowid=?', (rowid,))
            db.execute(f'DELETE FROM {table} WHERE rowid=?', (rowid,))

    async def upsert(self, collection: str, rows: Sequence[IndexRow], *, dimension: int | None) -> None:
        table = self._table(collection)

        def work():
            with self._connect() as db:
                self._ensure(db, table)
                for row in rows:
                    old = db.execute(f'SELECT rowid FROM {table} WHERE chunk_id=?', (row.chunk_id,)).fetchall()
                    self._delete_rowids(db, table, [r[0] for r in old])
                    blob, norm = _pack(row.vector) if row.vector is not None else (None, None)
                    if row.vector is not None and dimension is not None and len(row.vector) != dimension:
                        raise VectorStoreError('dimension_mismatch', 'vector size does not match the dimension')
                    cursor = db.execute(
                        f'INSERT INTO {table}(chunk_id, kb_id, version_id, dim, norm, vector) VALUES (?,?,?,?,?,?)',
                        (row.chunk_id, row.kb_id, row.version_id,
                         len(row.vector) if row.vector is not None else None, norm, blob))
                    if self.supports_keyword and row.tokens:
                        db.execute(f'INSERT INTO {table}_fts(rowid, tokens) VALUES (?, ?)',
                                   (cursor.lastrowid, row.tokens))
        await self._run(work)

    async def delete_versions(self, collection: str, version_ids: Sequence[str]) -> None:
        table = self._table(collection)

        def work():
            with self._connect() as db:
                if not self._exists(db, table):
                    return
                rowids = [r[0] for r in db.execute(
                    f'SELECT rowid FROM {table} WHERE version_id IN (SELECT value FROM json_each(?))',
                    (json.dumps(list(version_ids)),))]
                self._delete_rowids(db, table, rowids)
        await self._run(work)

    async def drop_collection(self, collection: str) -> None:
        table = self._table(collection)

        def work():
            with self._connect() as db:
                db.execute(f'DROP TABLE IF EXISTS {table}_fts')
                db.execute(f'DROP TABLE IF EXISTS {table}')
        await self._run(work)

    async def search_vector(self, collection: str, query: Sequence[float], scope: Scope, k: int) -> list[Candidate]:
        table = self._table(collection)
        if not scope.version_ids or k <= 0:
            return []
        q = [float(x) for x in query]
        q_norm = math.sqrt(sum(x * x for x in q))
        if q_norm == 0:
            raise VectorStoreError('invalid_query', 'query vector cannot be zero')

        def work():
            with self._connect() as db:
                if not self._exists(db, table):
                    return []
                rows = db.execute(
                    f'SELECT chunk_id, norm, vector FROM {table} WHERE vector IS NOT NULL AND dim=? '
                    'AND version_id IN (SELECT value FROM json_each(?))',
                    (len(q), json.dumps(list(scope.version_ids)))).fetchall()
            scored = []
            for chunk_id, norm, blob in rows:
                if not norm:
                    continue
                vector = _unpack(blob)
                cosine = sum(a * b for a, b in zip(q, vector)) / (q_norm * norm)
                scored.append(Candidate(chunk_id, max(0.0, min(1.0, cosine))))  # negative similarity is no match
            scored.sort(key=lambda c: (-c.score, c.chunk_id))
            return scored[:k]
        return await self._run(work)

    async def search_keyword(self, collection: str, tokens: Sequence[str], scope: Scope, k: int) -> list[Candidate]:
        table = self._table(collection)
        if not self.supports_keyword or not tokens or not scope.version_ids or k <= 0:
            return []
        match = ' OR '.join('"' + token.replace('"', '') + '"' for token in tokens if token)

        def work():
            with self._connect() as db:
                if not self._exists(db, table):
                    return []
                rows = db.execute(
                    f'SELECT t.chunk_id, -bm25({table}_fts) AS score FROM {table}_fts f '
                    f'JOIN {table} t ON t.rowid = f.rowid WHERE {table}_fts MATCH ? '
                    'AND t.version_id IN (SELECT value FROM json_each(?)) ORDER BY score DESC LIMIT ?',
                    (match, json.dumps(list(scope.version_ids)), k)).fetchall()
            return [Candidate(chunk_id, float(score)) for chunk_id, score in rows if score > 0]
        return await self._run(work)


register_engine('sqlite', SqliteVectorIndex, verified=True)
