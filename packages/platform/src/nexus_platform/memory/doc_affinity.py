"""Document affinity (openspec 2026-11-06-memory-evolution stage 6, D5; WeKnora ``memory_affinity.go``).

Documents a person's answers keep citing are probably the ones they care about. When a completed Run cites a
knowledge document, that person's counter for it grows by one (once per Run). Later searches by the same person
multiply the score of a document with at least :data:`MIN_HITS` citations by ``1 + 0.15 × min(hits, 8) / 8``
(at most 1.15), then re-sort. The boost is small on purpose: it breaks near ties, it never rescues an
irrelevant hit. Counting and boosting stop with the memory switches (space, member), and a deleted or
unreadable document is never in a result, so it cannot be boosted. Owners can list and clear their counters.
"""
from __future__ import annotations

from typing import Any, Iterable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus_core.platform import Principal, utc_now
from nexus_platform.memory.switches import memory_state
from nexus_platform.models.provider_settings import context
from nexus_platform.persistence.models import KnowledgeDocumentRecord, MemoryDocAffinityRecord

MIN_HITS = 2
HIT_CAP = 8
MAX_BOOST = 0.15


def factor(hits: int) -> float:
    """Score multiplier for ``hits`` citations; 1.0 below :data:`MIN_HITS`."""
    return 1.0 if hits < MIN_HITS else 1.0 + MAX_BOOST * min(hits, HIT_CAP) / HIT_CAP


def _available(db: Session, tenant_id: UUID, owner_id: UUID) -> bool:
    return memory_state(db, tenant_id=tenant_id, owner_id=owner_id).available


def record(db: Session, *, tenant_id: UUID, owner_id: UUID, document_ids: Iterable[str]) -> int:
    """Count one citation for each distinct existing document (caller's transaction); returns how many."""
    if not _available(db, tenant_id, owner_id):
        return 0
    ids = []
    for value in dict.fromkeys(document_ids):
        try:
            ids.append(UUID(str(value)))
        except ValueError:
            continue
    if not ids:
        return 0
    known = set(db.scalars(select(KnowledgeDocumentRecord.id).where(
        KnowledgeDocumentRecord.id.in_(ids), KnowledgeDocumentRecord.tenant_id == tenant_id)))
    now = utc_now()
    for document_id in ids:
        if document_id not in known:  # wiki pages and FAQ entries are not documents
            continue
        row = db.get(MemoryDocAffinityRecord, (tenant_id, owner_id, document_id))
        if row is None:
            db.add(MemoryDocAffinityRecord(tenant_id=tenant_id, owner_user_id=owner_id, document_id=document_id,
                                           hits=1, last_cited_at=now))
        else:
            row.hits, row.last_cited_at = row.hits + 1, now
    db.flush()
    return len(known & set(ids))


def boosts(db: Session, tenant_id: UUID, owner_id: UUID, document_ids: Iterable[str]) -> dict[str, float]:
    """``{document_id: multiplier}`` for the documents of a result that deserve a boost."""
    ids = []
    for value in document_ids:
        try:
            ids.append(UUID(str(value)))
        except ValueError:
            continue
    if not ids or not _available(db, tenant_id, owner_id):
        return {}
    rows = db.scalars(select(MemoryDocAffinityRecord).where(
        MemoryDocAffinityRecord.tenant_id == tenant_id, MemoryDocAffinityRecord.owner_user_id == owner_id,
        MemoryDocAffinityRecord.document_id.in_(ids), MemoryDocAffinityRecord.hits >= MIN_HITS))
    return {str(row.document_id): factor(row.hits) for row in rows}


def apply(db: Session, tenant_id: UUID, owner_id: UUID, hits: list) -> list:
    """Boost ``SearchHit`` scores of the caller's favourite documents and re-sort (stable for equal scores)."""
    wanted = boosts(db, tenant_id, owner_id, {h.document_id for h in hits if not h.chunk_id.startswith(('f:', 'w:'))})
    if not wanted:
        return hits
    for hit in hits:
        multiplier = wanted.get(hit.document_id)
        if multiplier:
            hit.score = round(hit.score * multiplier, 6)
            hit.ranks = {**hit.ranks, 'affinity': multiplier}
    return sorted(hits, key=lambda h: -h.score)


def list_affinity(db: Session, principal: Principal, tenant_id: UUID) -> list[dict[str, Any]]:
    """The caller's counters with document names (for "my memory"); documents that are gone are left out."""
    with db.begin():
        user, _ = context(db, principal, tenant_id)
        rows = db.scalars(select(MemoryDocAffinityRecord).where(
            MemoryDocAffinityRecord.tenant_id == tenant_id, MemoryDocAffinityRecord.owner_user_id == user.id)
            .order_by(MemoryDocAffinityRecord.hits.desc(), MemoryDocAffinityRecord.last_cited_at.desc()).limit(200)).all()
        docs = {d.id: d for d in db.scalars(select(KnowledgeDocumentRecord).where(
            KnowledgeDocumentRecord.id.in_([r.document_id for r in rows]), KnowledgeDocumentRecord.status == 'active'))}
        return [{'document_id': str(r.document_id), 'filename': docs[r.document_id].filename, 'hits': r.hits,
                 'boost': factor(r.hits), 'last_cited_at': r.last_cited_at.isoformat()}
                for r in rows if r.document_id in docs]


def clear(db: Session, principal: Principal, tenant_id: UUID, document_id: UUID | None = None) -> int:
    """Delete one counter, or all of the caller's counters when ``document_id`` is None."""
    with db.begin():
        user, _ = context(db, principal, tenant_id)
        query = select(MemoryDocAffinityRecord).where(MemoryDocAffinityRecord.tenant_id == tenant_id,
                                                      MemoryDocAffinityRecord.owner_user_id == user.id)
        if document_id is not None:
            query = query.where(MemoryDocAffinityRecord.document_id == document_id)
        rows = db.scalars(query).all()
        for row in rows:
            db.delete(row)
        return len(rows)
