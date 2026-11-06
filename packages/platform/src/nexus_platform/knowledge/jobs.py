"""Resumable knowledge jobs run by the worker (openspec 2026-11-06-knowledge-base K1.5).

``index`` job of one document version, one stage per transaction (Octop ``jobs.py`` pipeline with
WeKnora-style persisted progress):

1. ``pending`` → ``parsed``: read the original file, parse and chunk it, replace the version's chunks.
2. ``parsed`` → ``embedded``: write index rows in batches of :data:`BATCH`; with vector indexing each batch
   is embedded with the creator's key first. ``indexed_count`` is committed after every batch, so a crash
   resumes with the next batch (rows are upserted by chunk id, a repeated batch is harmless).
3. ``embedded`` → ``ready``: in one transaction the document's ``current_version_id`` moves to this version
   and the previous version becomes ``superseded``; its index rows are deleted afterwards.

Parse errors are permanent (``failed`` at once). Other errors back off 30 s, 2 min, 10 min and fail after
:data:`MAX_ATTEMPTS`. A version whose document or base is being deleted is cancelled.

``cleanup`` job: removes index rows, chunks, versions and original files of a deleted document, or of every
document of a deleted base (dropping its collection), then the rows themselves.

Claiming moves ``available_at`` forward by :data:`LEASE`, so two workers never run the same job at once and
a crashed worker's job becomes due again when the lease ends.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from nexus_core.platform import new_id, utc_now
from nexus_knowledge.index import IndexRow, collection_name
from nexus_knowledge.ingest.chunk import ChunkConfig, chunk_document
from nexus_knowledge.ingest.parse import ParseError, parse_document
from nexus_knowledge.text import tokenize
from nexus_platform.persistence.models import (KnowledgeBaseRecord, KnowledgeChunkRecord, KnowledgeDocumentRecord,
                                               KnowledgeDocumentVersionRecord, KnowledgeJobRecord)
from . import embedding, stores

logger = logging.getLogger(__name__)

BATCH = 32
MAX_ATTEMPTS = 4
BACKOFF = (30, 120, 600)
LEASE = timedelta(minutes=10)


class JobFailed(Exception):
    """Permanent failure with a stable code for the version's ``error_code``."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def claim(factory: sessionmaker[Session], limit: int = 1) -> list[UUID]:
    """Lease up to ``limit`` due jobs; returns their ids."""
    now = utc_now()
    with factory() as db, db.begin():
        rows = db.scalars(select(KnowledgeJobRecord).where(
            KnowledgeJobRecord.state == 'pending', KnowledgeJobRecord.available_at <= now)
            .order_by(KnowledgeJobRecord.available_at, KnowledgeJobRecord.created_at).limit(limit)
            .with_for_update(skip_locked=True)).all()
        for job in rows:
            job.available_at, job.updated_at = now + LEASE, now
        return [job.id for job in rows]


async def run_job(factory: sessionmaker[Session], job_id: UUID) -> str:
    """Run one claimed job to its end or to a failure; returns the final job state."""
    with factory() as db:
        job = db.get(KnowledgeJobRecord, job_id)
        kind = job.kind if job else None
    try:
        if kind == 'index':
            await _index(factory, job_id)
        elif kind == 'cleanup':
            await _cleanup(factory, job_id)
        else:
            return 'missing'
        return _finish(factory, job_id, 'done')
    except JobFailed as exc:
        _fail_version(factory, job_id, exc.code, str(exc))
        return _finish(factory, job_id, 'failed', str(exc))
    except _Cancelled:
        return _finish(factory, job_id, 'cancelled')
    except Exception as exc:  # retried with backoff, then failed
        logger.warning('knowledge job failed', extra={'job_id': str(job_id), 'error': type(exc).__name__})
        return _retry(factory, job_id, exc)


async def run_due(factory: sessionmaker[Session], limit: int = 1) -> int:
    """Claim and run due jobs sequentially; returns how many ran."""
    ids = claim(factory, limit)
    for job_id in ids:
        await run_job(factory, job_id)
    return len(ids)


class _Cancelled(Exception):
    pass


def _finish(factory, job_id: UUID, state: str, error: str | None = None) -> str:
    with factory() as db, db.begin():
        job = db.get(KnowledgeJobRecord, job_id)
        if job is not None:
            job.state, job.last_error, job.updated_at = state, error, utc_now()
            job.attempts += 1
    return state


def _retry(factory, job_id: UUID, exc: Exception) -> str:
    message = f'{type(exc).__name__}: {exc}'[:1000]
    with factory() as db, db.begin():
        job = db.get(KnowledgeJobRecord, job_id)
        if job is None:
            return 'missing'
        job.attempts += 1
        job.last_error, job.updated_at = message, utc_now()
        if job.attempts >= MAX_ATTEMPTS:
            job.state = 'failed'
            version = db.get(KnowledgeDocumentVersionRecord, job.version_id) if job.version_id else None
            if version is not None and version.state != 'ready':
                version.state, version.error_code = 'failed', getattr(exc, 'code', 'index_failed')
                version.error_message, version.updated_at = message, utc_now()
            return 'failed'
        job.available_at = utc_now() + timedelta(seconds=BACKOFF[min(job.attempts - 1, len(BACKOFF) - 1)])
        return 'pending'


def _fail_version(factory, job_id: UUID, code: str, message: str) -> None:
    with factory() as db, db.begin():
        job = db.get(KnowledgeJobRecord, job_id)
        version = db.get(KnowledgeDocumentVersionRecord, job.version_id) if job and job.version_id else None
        if version is not None:
            version.state, version.error_code, version.error_message = 'failed', code, message[:1000]
            version.updated_at = utc_now()


def _load(db: Session, job_id: UUID):
    job = db.get(KnowledgeJobRecord, job_id)
    version = db.get(KnowledgeDocumentVersionRecord, job.version_id)
    doc = db.get(KnowledgeDocumentRecord, version.document_id) if version else None
    kb = db.get(KnowledgeBaseRecord, job.kb_id)
    if version is None or doc is None or kb is None or doc.status != 'active' or kb.status != 'active':
        raise _Cancelled()
    return job, version, doc, kb


async def _index(factory, job_id: UUID) -> None:
    with factory() as db:
        _, version, doc, kb = _load(db, job_id)
        state = version.state
    if state in ('pending', 'failed'):
        await _parse(factory, job_id)
    with factory() as db:
        state = _load(db, job_id)[1].state
    if state == 'parsed':
        await _embed(factory, job_id)
    with factory() as db:
        state = _load(db, job_id)[1].state
    if state == 'embedded':
        await _activate(factory, job_id)


async def _parse(factory, job_id: UUID) -> None:
    with factory() as db:
        _, version, doc, kb = _load(db, job_id)
        blob = stores.blob_store_for(db, kb)
        key, filename = version.blob_key, doc.filename
        try:
            config = ChunkConfig.from_settings(kb.chunk_size, kb.chunk_overlap, (kb.settings or {}).get('chunking_config'))
        except ValueError as exc:
            raise JobFailed('invalid_chunking', str(exc)) from exc
    data = await blob.get(key)
    try:
        chunks = chunk_document(parse_document(filename, data), config)
    except ParseError as exc:
        raise JobFailed(exc.code, str(exc)) from exc
    with factory() as db, db.begin():
        _, version, _, kb = _load(db, job_id)
        db.execute(KnowledgeChunkRecord.__table__.delete().where(KnowledgeChunkRecord.version_id == version.id))
        ids = [new_id() for _ in chunks]  # a child names its parent by ordinal; parents come first
        db.add_all([KnowledgeChunkRecord(id=ids[c.ordinal], kb_id=kb.id, version_id=version.id, ordinal=c.ordinal,
                                         content=c.content, page=c.page, section=list(c.section),
                                         char_start=c.char_start, char_end=c.char_end,
                                         parent_id=ids[c.parent] if c.parent is not None else None,
                                         indexed=c.indexed) for c in chunks])
        # chunk_count counts what readers see: ordinary chunks or parents, not children.
        version.state, version.chunk_count, version.indexed_count = (
            'parsed', sum(1 for c in chunks if c.parent is None), 0)
        version.error_code = version.error_message = None
        version.updated_at = utc_now()


async def _embed(factory, job_id: UUID) -> None:
    while True:
        with factory() as db:
            _, version, _, kb = _load(db, job_id)
            # ``indexed_count`` counts the indexed rows (children or ordinary chunks) already written.
            rows = db.scalars(select(KnowledgeChunkRecord).where(
                KnowledgeChunkRecord.version_id == version.id, KnowledgeChunkRecord.indexed.is_(True))
                .order_by(KnowledgeChunkRecord.ordinal).offset(version.indexed_count).limit(BATCH)).all()
            batch = [(str(c.id), c.content, c.ordinal) for c in rows]
            index = stores.vector_index_for(db, kb)
            use_vectors = bool(kb.indexing.get('vector')) and kb.embedding_model_version_id is not None
            keyword = bool(kb.indexing.get('keyword'))
            ids = (kb.tenant_id, kb.created_by, kb.embedding_model_version_id, kb.id, kb.embedding_dimension)
            version_id = version.id
        if not batch:
            with factory() as db, db.begin():
                _load(db, job_id)[1].state = 'embedded'
            return
        tenant_id, owner_id, model_id, kb_id, dimension = ids
        vectors: list[list[float]] | list[None] = [None] * len(batch)
        if use_vectors:
            client = embedding.embedder(factory, tenant_id, owner_id, model_id, 'knowledge.embedding')
            try:
                vectors = await client.embed([text for _, text, _ in batch])
            finally:
                await client.close()
            if len(vectors) != len(batch) or not vectors[0]:
                raise RuntimeError('embedding response does not match the batch')
            if dimension is not None and len(vectors[0]) != dimension:
                raise JobFailed('dimension_mismatch',
                                f'embedding size {len(vectors[0])} differs from the base ({dimension}); rebuild the base')
            dimension = len(vectors[0])
        try:
            await index.upsert(collection_name(str(kb_id)), [
                IndexRow(chunk_id, str(kb_id), str(version_id), tokenize(text) if keyword else '', vector)
                for (chunk_id, text, _), vector in zip(batch, vectors)], dimension=dimension if use_vectors else None)
        finally:
            await index.close()
        with factory() as db, db.begin():
            _, version, _, kb = _load(db, job_id)
            version.indexed_count += len(batch)
            version.updated_at = utc_now()
            if use_vectors and kb.embedding_dimension is None:
                kb.embedding_dimension = dimension


async def _activate(factory, job_id: UUID) -> None:
    previous = None
    with factory() as db, db.begin():
        _, version, doc, kb = _load(db, job_id)
        if doc.current_version_id and doc.current_version_id != version.id:
            old = db.get(KnowledgeDocumentVersionRecord, doc.current_version_id)
            if old is not None:
                old.state, old.updated_at = 'superseded', utc_now()
                previous = old.id
        doc.current_version_id, doc.updated_at = version.id, utc_now()
        version.state, version.updated_at = 'ready', utc_now()
        from .graph.build import schedule
        schedule(db, kb, kb.created_by)  # a base with a graph rebuilds it after a document change
        index = stores.vector_index_for(db, kb)
        kb_id = kb.id
    if previous is not None:
        try:
            await index.delete_versions(collection_name(str(kb_id)), [str(previous)])
        finally:
            await index.close()
        with factory() as db, db.begin():
            db.execute(KnowledgeChunkRecord.__table__.delete().where(KnowledgeChunkRecord.version_id == previous))


async def _cleanup(factory, job_id: UUID) -> None:
    with factory() as db:
        job = db.get(KnowledgeJobRecord, job_id)
        kb = db.get(KnowledgeBaseRecord, job.kb_id)
        if kb is None:
            return
        whole_base = job.document_id is None
        query = select(KnowledgeDocumentVersionRecord).where(KnowledgeDocumentVersionRecord.kb_id == kb.id)
        if not whole_base:
            query = query.where(KnowledgeDocumentVersionRecord.document_id == job.document_id)
        versions = [(v.id, v.blob_key) for v in db.scalars(query)]
        index = stores.vector_index_for(db, kb)
        blob = stores.blob_store_for(db, kb)
        kb_id, document_id = kb.id, job.document_id
    try:
        if whole_base:
            await index.drop_collection(collection_name(str(kb_id)))
        elif versions:
            await index.delete_versions(collection_name(str(kb_id)), [str(v) for v, _ in versions])
    finally:
        await index.close()
    for _, key in versions:
        await blob.delete(key)
    # Child rows are deleted explicitly: SQLite deployments do not enforce ON DELETE CASCADE.
    version_ids = [v for v, _ in versions]
    with factory() as db, db.begin():
        if version_ids:
            db.execute(KnowledgeChunkRecord.__table__.delete().where(KnowledgeChunkRecord.version_id.in_(version_ids)))
            db.execute(KnowledgeDocumentVersionRecord.__table__.delete().where(
                KnowledgeDocumentVersionRecord.id.in_(version_ids)))
        if whole_base:
            row = db.get(KnowledgeBaseRecord, kb_id)
            if row is not None and row.status == 'deleting':
                db.execute(KnowledgeDocumentRecord.__table__.delete().where(KnowledgeDocumentRecord.kb_id == kb_id))
                from nexus_platform.persistence.models import FaqEntryRecord
                db.execute(FaqEntryRecord.__table__.delete().where(FaqEntryRecord.kb_id == kb_id))
                db.execute(KnowledgeJobRecord.__table__.delete().where(
                    KnowledgeJobRecord.kb_id == kb_id, KnowledgeJobRecord.id != job_id))
                db.delete(row)
        else:
            row = db.get(KnowledgeDocumentRecord, document_id)
            if row is not None and row.status == 'deleting':
                db.delete(row)
