"""FAQ knowledge bases: entries, import/export, indexing and cleanup (openspec 2026-11-06-knowledge-base K3).

Entries live in ``knowledge_faq_entries``; their index rows are written to the base's vector store (one or several
rows per entry according to ``settings['faq_config']``), with the entry id as the row's "version" so the common
Pre-Filter scope works unchanged: the scope of a FAQ base is the ids of its active, enabled, indexed entries.
Editing an entry takes it out of search until the worker has re-indexed it.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any, Mapping, Sequence
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, sessionmaker

from nexus_core.platform import new_id, utc_now
from nexus_knowledge import faq as rules
from nexus_knowledge.index import IndexRow, collection_name
from nexus_knowledge.text import tokenize
from nexus_platform.authz.audit import audit
from nexus_platform.errors import Conflict, NotFound
from nexus_platform.persistence.models import FaqEntryRecord, KnowledgeBaseRecord, KnowledgeTagRecord
from . import access, embedding, stores

logger = logging.getLogger(__name__)

MAX_IMPORT = 5000
INDEX_BATCH = 20
MAX_ATTEMPTS = 3
DEFAULT_CONFIG = {'index_mode': 'question_only', 'question_index_mode': 'combined'}


def faq_config(kb: KnowledgeBaseRecord) -> dict[str, str]:
    raw = (kb.settings or {}).get('faq_config') or {}
    return {'index_mode': raw.get('index_mode') if raw.get('index_mode') in rules.INDEX_MODES
            else DEFAULT_CONFIG['index_mode'],
            'question_index_mode': raw.get('question_index_mode') if raw.get('question_index_mode') in rules.QUESTION_MODES
            else DEFAULT_CONFIG['question_index_mode']}


def validate_config(settings: Mapping[str, Any] | None) -> None:
    raw = (settings or {}).get('faq_config') or {}
    if raw.get('index_mode', 'question_only') not in rules.INDEX_MODES:
        raise ValueError(f'faq_config.index_mode must be one of {", ".join(rules.INDEX_MODES)}')
    if raw.get('question_index_mode', 'combined') not in rules.QUESTION_MODES:
        raise ValueError(f'faq_config.question_index_mode must be one of {", ".join(rules.QUESTION_MODES)}')


def view(entry: FaqEntryRecord) -> dict[str, Any]:
    return {'id': str(entry.id), 'kb_id': str(entry.kb_id), 'category': entry.category, 'tag_id': str(entry.tag_id) if entry.tag_id else None,
            'standard_question': entry.standard_question, 'similar_questions': list(entry.similar_questions),
            'negative_questions': list(entry.negative_questions), 'answers': list(entry.answers),
            'answer_strategy': entry.answer_strategy, 'is_enabled': entry.enabled, 'is_recommended': entry.recommended,
            'index_state': entry.index_state, 'index_error': entry.index_error,
            'created_at': entry.created_at.isoformat(), 'updated_at': entry.updated_at.isoformat()}


def _faq_base(db: Session, tenant_id: UUID, user_id: UUID, kb_id: UUID, *, write: bool) -> KnowledgeBaseRecord:
    kb = (access.writable_base if write else access.readable_base)(db, kb_id, tenant_id, user_id)
    if kb.kb_type != 'faq':
        raise Conflict('This knowledge base is not a FAQ base')
    return kb


def _taken(db: Session, kb_id: UUID, exclude: Sequence[UUID] = ()) -> tuple[dict[str, str], dict[str, str]]:
    standard: dict[str, str] = {}
    similar: dict[str, str] = {}
    for row in db.scalars(select(FaqEntryRecord).where(FaqEntryRecord.kb_id == kb_id, FaqEntryRecord.status == 'active')):
        if row.id in exclude:
            continue
        standard[row.question_key] = str(row.id)
        for question in row.similar_questions:
            similar[rules.key(question)] = str(row.id)
    return standard, similar


def _apply(row: FaqEntryRecord, entry: rules.FaqInput) -> None:
    row.standard_question, row.question_key = entry.standard_question, rules.key(entry.standard_question)
    row.similar_questions, row.negative_questions = list(entry.similar_questions), list(entry.negative_questions)
    row.answers, row.answer_strategy, row.category = list(entry.answers), entry.answer_strategy, entry.category
    row.enabled, row.recommended = entry.enabled, entry.recommended
    row.index_state, row.index_attempts, row.index_error = 'pending', 0, None
    row.updated_at = utc_now()


def _tag_of(db: Session, kb: KnowledgeBaseRecord, value: Any) -> UUID | None:
    """A tag of this base by id; None clears. Unknown ids are rejected."""
    if value in (None, ''):
        return None
    try:
        tag = db.get(KnowledgeTagRecord, UUID(str(value)))
    except ValueError:
        tag = None
    if tag is None or tag.kb_id != kb.id:
        raise NotFound('Tag not found')
    return tag.id


def _tag_by_category(db: Session, kb: KnowledgeBaseRecord, category: str, cache: dict[str, UUID]) -> UUID | None:
    """The tag named like an imported category, created on first use (WeKnora turns the 分类 column into tags)."""
    name = ' '.join((category or '').split())[:120]
    if not name:
        return None
    key = name.casefold()
    if key not in cache:
        existing = db.scalar(select(KnowledgeTagRecord).where(KnowledgeTagRecord.kb_id == kb.id,
                                                              func.lower(KnowledgeTagRecord.name) == key))
        if existing is None:
            existing = KnowledgeTagRecord(id=new_id(), tenant_id=kb.tenant_id, kb_id=kb.id, name=name, color='',
                                          sort_order=0, created_by=kb.created_by, created_at=utc_now())
            db.add(existing)
            db.flush()
        cache[key] = existing.id
    return cache[key]


def create_entry(db: Session, tenant_id: UUID, user_id: UUID, kb_id: UUID, payload: Mapping[str, Any]) -> tuple[FaqEntryRecord, list[str]]:
    kb = _faq_base(db, tenant_id, user_id, kb_id, write=True)
    resolved = rules.resolve(rules.normalize(payload), *_taken(db, kb.id))
    if resolved.entry is None:
        raise Conflict(resolved.reason)
    now = utc_now()
    row = FaqEntryRecord(id=new_id(), tenant_id=kb.tenant_id, kb_id=kb.id, created_by=user_id, created_at=now, updated_at=now,
                         status='active', standard_question='', question_key='', answers=[], similar_questions=[],
                         negative_questions=[], answer_strategy='all', enabled=True, recommended=False,
                         index_state='pending', index_attempts=0)
    _apply(row, resolved.entry)
    row.tag_id = _tag_of(db, kb, payload.get('tag_id'))
    db.add(row)
    db.flush()
    audit(db, tenant_id, user_id, 'faq_entry.created', 'faq_entry', str(row.id), {'kb_id': str(kb.id)})
    return row, resolved.notes


def _entry(db: Session, kb: KnowledgeBaseRecord, entry_id: UUID) -> FaqEntryRecord:
    row = db.get(FaqEntryRecord, entry_id)
    if row is None or row.kb_id != kb.id or row.status != 'active':
        raise NotFound('FAQ entry not found')
    return row


def update_entry(db: Session, tenant_id: UUID, user_id: UUID, kb_id: UUID, entry_id: UUID,
                 payload: Mapping[str, Any]) -> tuple[FaqEntryRecord, list[str]]:
    kb = _faq_base(db, tenant_id, user_id, kb_id, write=True)
    row = _entry(db, kb, entry_id)
    resolved = rules.resolve(rules.normalize(payload), *_taken(db, kb.id, [row.id]), own_id=str(row.id))
    if resolved.entry is None:
        raise Conflict(resolved.reason)
    _apply(row, resolved.entry)
    if 'tag_id' in payload:
        row.tag_id = _tag_of(db, kb, payload.get('tag_id'))
    audit(db, tenant_id, user_id, 'faq_entry.updated', 'faq_entry', str(row.id), {'kb_id': str(kb.id)})
    return row, resolved.notes


def batch_fields(db: Session, tenant_id: UUID, user_id: UUID, kb_id: UUID, ids: Sequence[UUID],
                 changes: Mapping[str, Any]) -> int:
    """Enable/disable or (un)recommend entries; enabling keeps the index, so no re-index is needed."""
    kb = _faq_base(db, tenant_id, user_id, kb_id, write=True)
    count = 0
    for row in db.scalars(select(FaqEntryRecord).where(FaqEntryRecord.kb_id == kb.id, FaqEntryRecord.status == 'active',
                                                       FaqEntryRecord.id.in_(list(ids)))):
        if 'is_enabled' in changes:
            row.enabled = bool(changes['is_enabled'])
        if 'is_recommended' in changes:
            row.recommended = bool(changes['is_recommended'])
        if 'tag_id' in changes:
            row.tag_id = _tag_of(db, kb, changes['tag_id'])
        row.updated_at = utc_now()
        count += 1
    return count


def delete_entries(db: Session, tenant_id: UUID, user_id: UUID, kb_id: UUID, ids: Sequence[UUID]) -> int:
    """Mark entries deleted (immediately invisible to search); the worker removes index rows and the entries."""
    kb = _faq_base(db, tenant_id, user_id, kb_id, write=True)
    count = 0
    for row in db.scalars(select(FaqEntryRecord).where(FaqEntryRecord.kb_id == kb.id, FaqEntryRecord.status == 'active',
                                                       FaqEntryRecord.id.in_(list(ids)))):
        row.status, row.updated_at = 'deleting', utc_now()
        count += 1
    audit(db, tenant_id, user_id, 'faq_entry.deleted', 'knowledge_base', str(kb.id), {'count': count})
    return count


def list_entries(db: Session, tenant_id: UUID, user_id: UUID, kb_id: UUID, *, keyword: str = '', enabled: bool | None = None,
                 tag_ids: Sequence[str] = (), offset: int = 0, limit: int = 20) -> tuple[list[FaqEntryRecord], int]:
    kb = _faq_base(db, tenant_id, user_id, kb_id, write=False)
    query = select(FaqEntryRecord).where(FaqEntryRecord.kb_id == kb.id, FaqEntryRecord.status == 'active')
    if keyword:
        escaped = keyword.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
        like = f'%{escaped}%'
        query = query.where(or_(FaqEntryRecord.standard_question.ilike(like, escape='\\'),
                                FaqEntryRecord.category.ilike(like, escape='\\')))
    if enabled is not None:
        query = query.where(FaqEntryRecord.enabled.is_(enabled))
    if tag_ids:
        query = query.where(FaqEntryRecord.tag_id.in_([UUID(t) for t in tag_ids]))
    total = db.execute(select(func.count()).select_from(query.subquery())).scalar_one()
    rows = db.scalars(query.order_by(FaqEntryRecord.created_at.desc(), FaqEntryRecord.id).offset(max(0, offset))
                      .limit(max(1, min(limit, 200)))).all()
    return list(rows), total


def import_entries(db: Session, tenant_id: UUID, user_id: UUID, kb_id: UUID, rows: Sequence[Mapping[str, Any]],
                   mode: str) -> dict[str, Any]:
    """Import rows with the conflict rules; ``replace`` deletes the existing entries first.

    Returns ``{created, blocked: [{index, standard_question, reason}], notes: [...]}``. Blocked rows are not
    imported and the rest are (WeKnora dry-run semantics, without a separate dry-run step).
    """
    if mode not in ('append', 'replace'):
        raise ValueError("mode must be 'append' or 'replace'")
    if len(rows) > MAX_IMPORT:
        raise ValueError(f'at most {MAX_IMPORT} entries per import')
    kb = _faq_base(db, tenant_id, user_id, kb_id, write=True)
    if mode == 'replace':
        for row in db.scalars(select(FaqEntryRecord).where(FaqEntryRecord.kb_id == kb.id, FaqEntryRecord.status == 'active')):
            row.status, row.updated_at = 'deleting', utc_now()
    standard, similar = _taken(db, kb.id)
    created, blocked, notes = 0, [], []
    now = utc_now()
    tag_cache: dict[str, UUID] = {}
    for index, raw in enumerate(rows, start=1):
        try:
            resolved = rules.resolve(rules.normalize(raw), standard, similar)
        except ValueError as exc:
            blocked.append({'index': index, 'standard_question': str(raw.get('standard_question') or ''), 'reason': str(exc)})
            continue
        if resolved.entry is None:
            blocked.append({'index': index, 'standard_question': str(raw.get('standard_question') or ''),
                            'reason': resolved.reason})
            continue
        entry = FaqEntryRecord(id=new_id(), tenant_id=kb.tenant_id, kb_id=kb.id, created_by=user_id, created_at=now,
                               updated_at=now, status='active', standard_question='', question_key='', answers=[],
                               similar_questions=[], negative_questions=[], answer_strategy='all', enabled=True,
                               recommended=False, index_state='pending', index_attempts=0)
        _apply(entry, resolved.entry)
        entry.tag_id = _tag_by_category(db, kb, resolved.entry.category, tag_cache)
        db.add(entry)
        standard[entry.question_key] = str(entry.id)
        for question in entry.similar_questions:
            similar[rules.key(question)] = str(entry.id)
        created += 1
        notes += [f'第 {index} 行：{note}' for note in resolved.notes]
    audit(db, tenant_id, user_id, 'faq_entry.imported', 'knowledge_base', str(kb.id),
          {'created': created, 'blocked': len(blocked), 'mode': mode})
    return {'created': created, 'blocked': blocked, 'notes': notes}


def export_entries(db: Session, tenant_id: UUID, user_id: UUID, kb_id: UUID) -> list[dict[str, Any]]:
    kb = _faq_base(db, tenant_id, user_id, kb_id, write=False)
    return [{'category': r.category, 'standard_question': r.standard_question, 'similar_questions': r.similar_questions,
             'negative_questions': r.negative_questions, 'answers': r.answers, 'answer_strategy': r.answer_strategy,
             'enabled': r.enabled} for r in db.scalars(select(FaqEntryRecord).where(
                 FaqEntryRecord.kb_id == kb.id, FaqEntryRecord.status == 'active').order_by(FaqEntryRecord.created_at))]


def scope_ids(db: Session, kb_id: UUID, tag_ids: Sequence[str] | None = None) -> tuple[str, ...]:
    """Entries a search may return: active, enabled and indexed (optionally with one of the given tags)."""
    query = select(FaqEntryRecord.id).where(
        FaqEntryRecord.kb_id == kb_id, FaqEntryRecord.status == 'active', FaqEntryRecord.enabled.is_(True),
        FaqEntryRecord.index_state == 'ready')
    if tag_ids:
        query = query.where(FaqEntryRecord.tag_id.in_([UUID(t) for t in tag_ids]))
    return tuple(sorted(str(i) for i in db.scalars(query)))


# ---------------------------------------------------------------- worker

async def index_tick(factory: sessionmaker[Session], limit: int = INDEX_BATCH) -> int:
    """Index pending entries and remove deleted ones; returns how many entries were handled."""
    handled = await _cleanup(factory, limit)
    with factory() as db:
        pending = db.execute(select(FaqEntryRecord.id, FaqEntryRecord.kb_id).where(
            FaqEntryRecord.status == 'active', FaqEntryRecord.index_state == 'pending')
            .order_by(FaqEntryRecord.kb_id, FaqEntryRecord.updated_at).limit(limit)).all()
    by_kb: dict[UUID, list[UUID]] = {}
    for entry_id, kb_id in pending:
        by_kb.setdefault(kb_id, []).append(entry_id)
    for kb_id, ids in by_kb.items():
        handled += await _index_base(factory, kb_id, ids)
    return handled


async def _index_base(factory, kb_id: UUID, ids: list[UUID]) -> int:
    with factory() as db:
        kb = db.get(KnowledgeBaseRecord, kb_id)
        if kb is None or kb.status != 'active':
            return 0
        entries = [(r.id, r.standard_question, list(r.similar_questions), list(r.answers))
                   for r in db.scalars(select(FaqEntryRecord).where(FaqEntryRecord.id.in_(ids),
                                                                    FaqEntryRecord.status == 'active'))]
        config = faq_config(kb)
        use_vectors = bool(kb.indexing.get('vector')) and kb.embedding_model_version_id is not None
        keyword = bool(kb.indexing.get('keyword'))
        ctx = (kb.tenant_id, kb.created_by, kb.embedding_model_version_id, kb.embedding_dimension)
        index = stores.vector_index_for(db, kb)
    tenant_id, owner_id, model_id, dimension = ctx
    collection = collection_name(str(kb_id))
    rows_by_entry: dict[UUID, list[tuple[str, str]]] = {}
    flat: list[str] = []
    for entry_id, question, similar, answers in entries:
        texts = rules.index_texts(question, similar, answers, config['index_mode'], config['question_index_mode'])
        rows_by_entry[entry_id] = [(f'f:{entry_id}:{n}', text) for n, text in enumerate(texts)]
        flat.extend(texts)
    error: Exception | None = None
    vectors: list[list[float]] = []
    try:
        if use_vectors and flat:
            client = embedding.embedder(factory, tenant_id, owner_id, model_id, 'knowledge.embedding')
            try:
                vectors = await client.embed(flat)
            finally:
                await client.close()
            if vectors and dimension and len(vectors[0]) != dimension:
                raise ValueError('embedding size differs from the base; rebuild the base')
            dimension = len(vectors[0]) if vectors else dimension
        await index.delete_versions(collection, [str(e[0]) for e in entries])
        cursor = 0
        out = []
        for entry_id, _, _, _ in entries:
            for chunk_id, text in rows_by_entry[entry_id]:
                out.append(IndexRow(chunk_id, str(kb_id), str(entry_id), tokenize(text) if keyword else '',
                                    vectors[cursor] if use_vectors else None))
                cursor += 1
        if out:
            await index.upsert(collection, out, dimension=dimension if use_vectors else None)
    except Exception as exc:
        error = exc
        logger.warning('faq indexing failed', extra={'kb_id': str(kb_id), 'error': type(exc).__name__})
    finally:
        await index.close()
    with factory() as db, db.begin():
        kb = db.get(KnowledgeBaseRecord, kb_id)
        if kb is not None and error is None and use_vectors and kb.embedding_dimension is None:
            kb.embedding_dimension = dimension
        for entry_id, *_ in entries:
            row = db.get(FaqEntryRecord, entry_id)
            if row is None or row.status != 'active':
                continue
            if error is None:
                row.index_state, row.index_error = 'ready', None
            else:
                row.index_attempts += 1
                row.index_error = f'{type(error).__name__}: {error}'[:1000]
                row.index_state = 'failed' if row.index_attempts >= MAX_ATTEMPTS else 'pending'
    return len(entries)


async def _cleanup(factory, limit: int) -> int:
    with factory() as db:
        doomed = db.execute(select(FaqEntryRecord.id, FaqEntryRecord.kb_id).where(FaqEntryRecord.status == 'deleting')
                            .limit(limit)).all()
    by_kb: dict[UUID, list[UUID]] = {}
    for entry_id, kb_id in doomed:
        by_kb.setdefault(kb_id, []).append(entry_id)
    for kb_id, ids in by_kb.items():
        with factory() as db:
            kb = db.get(KnowledgeBaseRecord, kb_id)
            index = stores.vector_index_for(db, kb) if kb is not None else None
        if index is not None:
            try:
                await index.delete_versions(collection_name(str(kb_id)), [str(i) for i in ids])
            except Exception:
                logger.warning('faq cleanup failed', extra={'kb_id': str(kb_id)})
                await index.close()
                continue
            await index.close()
        with factory() as db, db.begin():
            db.execute(FaqEntryRecord.__table__.delete().where(FaqEntryRecord.id.in_(ids)))
    return len(doomed)


def retry_failed(db: Session, tenant_id: UUID, user_id: UUID, kb_id: UUID) -> int:
    kb = _faq_base(db, tenant_id, user_id, kb_id, write=True)
    count = 0
    for row in db.scalars(select(FaqEntryRecord).where(FaqEntryRecord.kb_id == kb.id, FaqEntryRecord.status == 'active',
                                                       FaqEntryRecord.index_state == 'failed')):
        row.index_state, row.index_attempts, row.index_error = 'pending', 0, None
        count += 1
    return count
