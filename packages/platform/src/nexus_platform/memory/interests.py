"""Interest topics (openspec 2026-11-06-memory-evolution stage 6, D4; WeKnora `observeTopics`).

A single mention is noise; the same subject across several conversations is a signal. Every capture
window reports the topics of its valid actions; each topic is counted once per conversation. When a
topic reaches the space's `interest_threshold`, an `interest` draft ("长期关注：<topic>") is proposed once.
The owner reviews it like any other draft (decision E2); rejecting it leaves a tombstone with the topic,
and a topic that was rejected is no longer counted.

Topics are matched by `nexus_memory.text.topic_key` only (no model call); other wordings that resolve to
the same key are kept as aliases.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Iterable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus_core.platform import Principal, new_id, utc_now
from nexus_memory import service as memory_rules
from nexus_memory import text as memtext
from nexus_platform.models.provider_settings import context
from nexus_platform.persistence.models import MemorySpaceSettingsRecord, MemoryTopicStatRecord

from .repository import SqlMemoryRepository

DEFAULT_THRESHOLD = 3
THRESHOLD_RANGE = (2, 10)
#: Conversations remembered per topic (enough to count distinct ones near any threshold).
SESSION_LIMIT = 50
#: How far back a rejected topic stops counting.
REJECTED_WINDOW = timedelta(days=3650)


def threshold(db: Session, tenant_id: UUID) -> int:
    row = db.get(MemorySpaceSettingsRecord, tenant_id)
    return row.interest_threshold if row and row.interest_threshold else DEFAULT_THRESHOLD


def observe(db: Session, *, tenant_id: UUID, owner_id: UUID, session_id: UUID, run_id: UUID,
            topics: Iterable[str], now: datetime | None = None) -> list[str]:
    """Count `topics` for this conversation; returns the topics proposed as interests now (caller transaction)."""
    now = now or utc_now()
    repo = SqlMemoryRepository(db)
    declined = {memtext.topic_key(topic) for topic in repo.rejected_topics(tenant_id, owner_id, now - REJECTED_WINDOW, 1000)}
    limit = threshold(db, tenant_id)
    promoted: list[str] = []
    seen: set[str] = set()
    for topic in topics:
        topic = (topic or '').strip()[:160]
        key = memtext.topic_key(topic)
        if not key or key in seen or key in declined:
            continue
        seen.add(key)
        row = db.scalar(select(MemoryTopicStatRecord).where(
            MemoryTopicStatRecord.tenant_id == tenant_id, MemoryTopicStatRecord.owner_user_id == owner_id,
            MemoryTopicStatRecord.normalized_key == key).with_for_update())
        if row is None:
            row = MemoryTopicStatRecord(id=new_id(), tenant_id=tenant_id, owner_user_id=owner_id, normalized_key=key,
                                        topic=topic, aliases=[], session_ids=[], hits=0, last_seen_at=now)
            db.add(row)
        sessions = list(row.session_ids or [])
        if str(session_id) not in sessions:
            sessions = (sessions + [str(session_id)])[-SESSION_LIMIT:]
            row.session_ids = sessions
            row.hits = (row.hits or 0) + 1
        if topic != row.topic and topic not in (row.aliases or []):
            row.aliases = list(row.aliases or []) + [topic]
        row.last_seen_at = now
        if row.promoted_at is None and row.hits >= limit:
            outcome = memory_rules.propose(repo, tenant_id, owner_id, run_id, 'interest', f'长期关注：{row.topic}',
                                           origin='capture', topic=row.topic)
            row.promoted_at = now
            if outcome['status'] == 'pending':
                promoted.append(row.topic)
    db.flush()
    return promoted


def list_topics(db: Session, principal: Principal, tenant_id: UUID) -> list[dict[str, Any]]:
    """The caller's counted topics, most frequent first (for "my memory")."""
    with db.begin():
        user, _ = context(db, principal, tenant_id)
        rows = db.scalars(select(MemoryTopicStatRecord).where(
            MemoryTopicStatRecord.tenant_id == tenant_id, MemoryTopicStatRecord.owner_user_id == user.id)
            .order_by(MemoryTopicStatRecord.hits.desc(), MemoryTopicStatRecord.last_seen_at.desc()).limit(100))
        return [{'id': str(row.id), 'topic': row.topic, 'aliases': list(row.aliases or []), 'hits': row.hits,
                 'threshold': threshold(db, tenant_id), 'promoted': row.promoted_at is not None,
                 'last_seen_at': row.last_seen_at.isoformat()} for row in rows]
