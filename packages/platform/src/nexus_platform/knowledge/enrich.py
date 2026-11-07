"""LLM enrichment of indexed documents (openspec 2026-11-06-knowledge-base K5.2).

After a document version becomes ``ready`` a base with enrichment settings queues an ``enrich`` job. The job runs
the enabled steps, each idempotent and recorded in ``version.enrichment`` so a retry resumes after the last
finished step:

- ``summary``: a short summary of the document (needs ``settings.summary_model_id``);
- ``questions``: questions each chunk can answer (``question_generation_config``); every question becomes an extra
  index row (``q:<chunk>:<n>``) that resolves back to its chunk, so a user's phrasing finds text that never says it;
- ``tags``: the model picks existing tags or proposes new ones (``auto_tag_config``).

A job without a version regenerates the base profile (``profile_config``): a short description built from the
document summaries, stored in ``settings.generated_profile`` and shown to agents in the knowledge catalog.

All model calls use the knowledge base creator's key (decision 6). Enrichment never changes what is searchable by
itself except by adding question rows; a failing step is retried with backoff and never marks the version failed.
"""
from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from nexus_core.platform import new_id, utc_now
from nexus_knowledge import enrich as prompts
from nexus_knowledge.index import IndexRow, collection_name
from nexus_knowledge.text import tokenize
from nexus_platform.persistence.models import (KnowledgeBaseRecord, KnowledgeChunkRecord, KnowledgeDocumentRecord,
                                               KnowledgeDocumentVersionRecord, KnowledgeJobRecord, KnowledgeTagRecord)
from . import embedding, stores
from .graph import llm

logger = logging.getLogger(__name__)

MAX_QUESTION_CHUNKS = 300
BATCH = 32
MAX_TAGS = 200


class EnrichFailed(Exception):
    """Permanent failure (configuration): the job fails without retrying and without touching the version."""


def _uuid(value: Any) -> UUID | None:
    try:
        return UUID(str(value)) if value else None
    except ValueError:
        return None


def models_of(settings: dict[str, Any] | None) -> dict[str, UUID | None]:
    """Model per step: its own model, else the base's summary model."""
    settings = settings or {}
    base = _uuid(settings.get('summary_model_id'))
    return {
        'summary': base,
        'questions': _uuid((settings.get('question_generation_config') or {}).get('model_id')) or base,
        'tags': _uuid((settings.get('auto_tag_config') or {}).get('model_id')) or base,
        'profile': _uuid((settings.get('profile_config') or {}).get('model_id')) or base,
    }


def steps_of(kb: KnowledgeBaseRecord) -> list[str]:
    """Enabled steps that have a model."""
    settings = kb.settings or {}
    models = models_of(settings)
    steps = []
    if models['summary']:
        steps.append('summary')
    if (settings.get('question_generation_config') or {}).get('enabled') and models['questions']:
        steps.append('questions')
    if (settings.get('auto_tag_config') or {}).get('enabled') and models['tags']:
        steps.append('tags')
    return steps


def profile_enabled(kb: KnowledgeBaseRecord) -> bool:
    return bool((kb.settings or {}).get('profile_config', {}).get('enabled')) and models_of(kb.settings)['profile'] is not None


def schedule(db: Session, kb: KnowledgeBaseRecord, version_id: UUID | None, document_id: UUID | None = None) -> None:
    """Queue an enrich job for a ready version (or, with no version, a profile refresh)."""
    if kb.kb_type not in ('document', 'wiki'):
        return
    if version_id is not None and not steps_of(kb) and not profile_enabled(kb):
        return
    if version_id is None and not profile_enabled(kb):
        return
    existing = db.scalar(select(KnowledgeJobRecord.id).where(
        KnowledgeJobRecord.kb_id == kb.id, KnowledgeJobRecord.kind == 'enrich', KnowledgeJobRecord.state == 'pending',
        KnowledgeJobRecord.version_id == version_id))
    if existing is not None:
        return
    now = utc_now()
    db.add(KnowledgeJobRecord(id=new_id(), tenant_id=kb.tenant_id, kb_id=kb.id, document_id=document_id,
                              version_id=version_id, kind='enrich', state='pending', attempts=0, available_at=now,
                              created_at=now, updated_at=now))


async def run(factory: sessionmaker[Session], job_id: UUID) -> None:
    with factory() as db:
        job = db.get(KnowledgeJobRecord, job_id)
        kb = db.get(KnowledgeBaseRecord, job.kb_id) if job else None
        if job is None or kb is None or kb.status != 'active':
            return
        version_id, kb_id = job.version_id, kb.id
    if version_id is not None:
        await _enrich_version(factory, version_id)
    await refresh_profile(factory, kb_id)  # no-op unless the base has the profile enabled


def _load(db: Session, version_id: UUID):
    version = db.get(KnowledgeDocumentVersionRecord, version_id)
    doc = db.get(KnowledgeDocumentRecord, version.document_id) if version else None
    kb = db.get(KnowledgeBaseRecord, version.kb_id) if version else None
    if version is None or doc is None or kb is None or doc.status != 'active' or kb.status != 'active' \
            or version.state != 'ready' or doc.current_version_id != version.id:
        return None
    return version, doc, kb


async def _enrich_version(factory, version_id: UUID) -> None:
    with factory() as db:
        loaded = _load(db, version_id)
        if loaded is None:
            return
        version, doc, kb = loaded
        steps = [s for s in steps_of(kb) if version.enrichment.get(s) != 'done']
        models = models_of(kb.settings)
    for step in steps:
        with factory() as db:
            if _load(db, version_id) is None:
                return  # the version was replaced or deleted meanwhile
        await {'summary': _summary, 'questions': _questions, 'tags': _tags}[step](factory, version_id, models[step])
        with factory() as db, db.begin():
            row = db.get(KnowledgeDocumentVersionRecord, version_id)
            row.enrichment = {**row.enrichment, step: 'done'}
            row.updated_at = utc_now()


def _chunks(db: Session, version_id: UUID, *, indexed: bool | None = None) -> list[KnowledgeChunkRecord]:
    query = select(KnowledgeChunkRecord).where(KnowledgeChunkRecord.version_id == version_id)
    query = query.where(KnowledgeChunkRecord.indexed.is_(True)) if indexed else query.where(KnowledgeChunkRecord.parent_id.is_(None))
    return list(db.scalars(query.order_by(KnowledgeChunkRecord.ordinal)))


async def _summary(factory, version_id: UUID, model: UUID) -> None:
    with factory() as db:
        version, doc, kb = _load(db, version_id)
        text = '\n\n'.join(c.content for c in _chunks(db, version_id))[:prompts.SUMMARY_CHARS]
        ids = (kb.tenant_id, kb.created_by, doc.filename)
    reply = await llm.complete(factory, ids[0], ids[1], model, 'knowledge.enrich', prompts.SUMMARY_SYSTEM,
                               prompts.summary_message(ids[2], text), 800)
    summary = prompts.parse_summary(reply)
    with factory() as db, db.begin():
        db.get(KnowledgeDocumentVersionRecord, version_id).summary = summary or None


async def _questions(factory, version_id: UUID, model: UUID) -> None:
    with factory() as db:
        version, doc, kb = _load(db, version_id)
        config = (kb.settings or {}).get('question_generation_config') or {}
        count = max(1, min(int(config.get('question_count') or 3), prompts.MAX_QUESTIONS))
        instructions = str(config.get('custom_instructions') or '')
        rows = [(c.id, c.content) for c in _chunks(db, version_id, indexed=True)][:MAX_QUESTION_CHUNKS]
        ctx = (kb.tenant_id, kb.created_by, kb.embedding_model_version_id, kb.id,
               bool(kb.indexing.get('vector')) and kb.embedding_model_version_id is not None,
               bool(kb.indexing.get('keyword')), kb.embedding_dimension)
        index = stores.vector_index_for(db, kb)
    tenant_id, owner_id, embed_model, kb_id, use_vectors, keyword, dimension = ctx
    system = prompts.questions_system(count, instructions)
    try:
        for start in range(0, len(rows), prompts.QUESTION_BATCH):
            batch = rows[start:start + prompts.QUESTION_BATCH]
            reply = await llm.complete(factory, tenant_id, owner_id, model, 'knowledge.enrich', system,
                                       prompts.questions_message([text for _, text in batch]), 1500)
            parsed = prompts.parse_questions(reply, len(batch), count)
            pairs = [(cid, question) for (cid, _), questions in zip(batch, parsed) for question in questions]
            if not pairs:
                continue
            vectors: list = [None] * len(pairs)
            if use_vectors:
                client = embedding.embedder(factory, tenant_id, owner_id, embed_model, 'knowledge.embedding')
                try:
                    vectors = await client.embed([q for _, q in pairs])
                finally:
                    await client.close()
                dimension = len(vectors[0]) if vectors and vectors[0] else dimension
            counters: dict[UUID, int] = {}
            index_rows = []
            for (cid, question), vector in zip(pairs, vectors):
                n = counters[cid] = counters.get(cid, -1) + 1
                index_rows.append(IndexRow(f'q:{cid}:{n}', str(kb_id), str(version_id),
                                           tokenize(question) if keyword else '', vector))
            await index.upsert(collection_name(str(kb_id)), index_rows, dimension=dimension if use_vectors else None)
            with factory() as db, db.begin():
                for (cid, _), questions in zip(batch, parsed):
                    chunk = db.get(KnowledgeChunkRecord, cid)
                    if chunk is not None:
                        chunk.questions = questions
    finally:
        await index.close()


async def _tags(factory, version_id: UUID, model: UUID) -> None:
    with factory() as db:
        version, doc, kb = _load(db, version_id)
        config = (kb.settings or {}).get('auto_tag_config') or {}
        if config.get('skip_if_tagged', True) and doc.tag_ids:
            return
        limit = max(1, min(int(config.get('max_tags') or 3), 10))
        existing = [t.name for t in db.scalars(select(KnowledgeTagRecord).where(KnowledgeTagRecord.kb_id == kb.id))]
        text = '\n\n'.join(c.content for c in _chunks(db, version_id)[:6])
        ctx = (kb.tenant_id, kb.created_by, kb.id, doc.id, doc.filename)
    reply = await llm.complete(factory, ctx[0], ctx[1], model, 'knowledge.enrich', prompts.tags_system(limit),
                               prompts.tags_message(ctx[4], text, existing), 400)
    names = prompts.parse_tags(reply, limit)
    if not names:
        return
    with factory() as db, db.begin():
        by_name = {t.name.casefold(): t for t in db.scalars(select(KnowledgeTagRecord).where(KnowledgeTagRecord.kb_id == ctx[2]))}
        ids = []
        for name in names:
            tag = by_name.get(name.casefold())
            if tag is None:
                if len(by_name) >= MAX_TAGS:
                    continue
                tag = KnowledgeTagRecord(id=new_id(), tenant_id=ctx[0], kb_id=ctx[2], name=name, color='', sort_order=0,
                                         created_by=ctx[1], created_at=utc_now())
                db.add(tag)
                by_name[name.casefold()] = tag
            ids.append(str(tag.id))
        document = db.get(KnowledgeDocumentRecord, ctx[3])
        document.tag_ids = list(dict.fromkeys([*(document.tag_ids or []), *ids]))


async def refresh_profile(factory, kb_id: UUID) -> str:
    """Regenerate ``settings.generated_profile`` from the documents' summaries (or first chunk text)."""
    with factory() as db:
        kb = db.get(KnowledgeBaseRecord, kb_id)
        if kb is None or kb.status != 'active' or not profile_enabled(kb):
            return ''
        config = (kb.settings or {}).get('profile_config') or {}
        model = models_of(kb.settings)['profile']
        docs = []
        for doc in db.scalars(select(KnowledgeDocumentRecord).where(
                KnowledgeDocumentRecord.kb_id == kb.id, KnowledgeDocumentRecord.status == 'active',
                KnowledgeDocumentRecord.current_version_id.is_not(None)).order_by(KnowledgeDocumentRecord.filename).limit(40)):
            version = db.get(KnowledgeDocumentVersionRecord, doc.current_version_id)
            first = db.scalar(select(KnowledgeChunkRecord.content).where(
                KnowledgeChunkRecord.version_id == doc.current_version_id, KnowledgeChunkRecord.parent_id.is_(None))
                .order_by(KnowledgeChunkRecord.ordinal).limit(1)) or ''
            docs.append((doc.filename, (version.summary if version and version.summary else first)[:200]))
        ctx = (kb.tenant_id, kb.created_by, kb.name, str(config.get('custom_instructions') or ''))
    if not docs:
        return ''
    reply = await llm.complete(factory, ctx[0], ctx[1], model, 'knowledge.enrich', prompts.PROFILE_SYSTEM,
                               prompts.profile_message(ctx[2], docs, ctx[3]), 600)
    description = prompts.parse_profile(reply)
    if description:
        with factory() as db, db.begin():
            row = db.get(KnowledgeBaseRecord, kb_id)
            row.settings = {**(row.settings or {}), 'generated_profile': {
                'description': description, 'updated_at': utc_now().isoformat()}}
    return description


def request_profile(db: Session, kb: KnowledgeBaseRecord) -> None:
    """Queue a profile refresh (manual button)."""
    if not profile_enabled(kb):
        raise ValueError('enable the knowledge base profile and choose a model first')
    schedule(db, kb, None)
