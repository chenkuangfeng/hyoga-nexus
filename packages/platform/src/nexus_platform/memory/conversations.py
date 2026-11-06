"""Search and page through the caller's past conversations (openspec 2026-11-06-memory-evolution stage 4, D1).

Curated memory is small and reviewed; this is the other half (hermes-agent `session_search`, WeKnora
`search_conversations`): the model can look up what was said in earlier sessions, word for word, without
any model summarization.

Scope and authorization, checked on every call:
- only sessions the caller owns in the Run's space, never the current session;
- only `user` and `assistant` messages (tool output and runtime notes are not conversation);
- a message produced by a Run whose resource grants were revoked is not returned (`histories_allowed`),
  the same rule that hides it from that session's own history; forked copies are checked against
  the Run they came from.
The tools belong to the memory group, so the memory switches remove them like the other memory tools.

Matching scans the caller's most recent `SCAN_LIMIT` messages and keeps those containing every query
token (`nexus_memory.text` tokens, CJK bigrams), ranked by how often the tokens occur, then by recency.
Personal history is small enough for this; a keyword index can replace the scan without changing the
contract.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus_memory import text as memtext
from nexus_platform.authz.audit import audit
from nexus_platform.persistence.models import MessageRecord, RunRecord, SessionRecord
from nexus_platform.runs.messages import histories_allowed

#: Most recent messages scanned per search.
SCAN_LIMIT = 5000
SNIPPET_CHARS = 160
#: Paging bounds for `read_page`: messages each side, characters per message, characters in total.
MAX_SIDE = 10
MESSAGE_CHARS = 1000
PAGE_CHARS = 8000
ROLES = ('user', 'assistant')


def _source_run(message: MessageRecord) -> UUID | None:
    if message.run_id is not None:
        return message.run_id
    origin = (message.runtime_metadata or {}).get('source_run_id')
    return UUID(str(origin)) if origin else None


def _visible(db: Session, messages: list[MessageRecord]) -> list[MessageRecord]:
    """Drop messages whose producing Run's history is no longer visible to its owner."""
    run_ids = {run_id for run_id in (_source_run(m) for m in messages) if run_id is not None}
    runs = list(db.scalars(select(RunRecord).where(RunRecord.id.in_(run_ids)))) if run_ids else []
    allowed = histories_allowed(db, runs)
    return [m for m in messages if (_source_run(m) is None) or allowed.get(_source_run(m), False)]


def search(db: Session, *, tenant_id: UUID, owner_id: UUID, current_session_id: UUID, query: str,
           limit: int = 5) -> list[dict[str, Any]]:
    """Messages from the owner's other sessions that contain every query token, best first."""
    tokens = memtext.query_tokens(query)
    if not tokens:
        return []
    limit = max(1, min(limit, 10))
    rows = db.execute(
        select(MessageRecord, SessionRecord.title)
        .join(SessionRecord, SessionRecord.id == MessageRecord.session_id)
        .where(SessionRecord.tenant_id == tenant_id, SessionRecord.owner_user_id == owner_id,
               SessionRecord.id != current_session_id, MessageRecord.role.in_(ROLES))
        .order_by(MessageRecord.created_at.desc()).limit(SCAN_LIMIT)).all()
    titles = {message.id: title for message, title in rows}
    scored = []
    for order, (message, _) in enumerate(rows):
        haystack = ' ' + memtext.tokenize(message.content) + ' '
        counts = [haystack.count(f' {t} ') if not memtext.is_single_cjk(t) else message.content.count(t) for t in tokens]
        if all(counts):
            scored.append((sum(counts), order, message))
    scored.sort(key=lambda row: (-row[0], row[1]))
    kept = _visible(db, [message for _, _, message in scored[:limit * 3]])[:limit]
    audit(db, tenant_id, owner_id, 'conversation.search', 'session', str(current_session_id),
          {'hits': len(kept), 'sessions': len({str(m.session_id) for m in kept})})
    return [{'session_id': str(m.session_id), 'session_title': titles[m.id], 'sequence': m.sequence,
             'role': m.role, 'snippet': _snippet(m.content, tokens), 'created_at': m.created_at.isoformat()}
            for m in kept]


def read_page(db: Session, *, tenant_id: UUID, owner_id: UUID, current_session_id: UUID, session_id: UUID,
              around: int, before: int = 5, after: int = 5) -> dict[str, Any] | None:
    """Messages around `around` in one of the owner's other sessions; None when not readable."""
    session = db.get(SessionRecord, session_id)
    if (session is None or session.tenant_id != tenant_id or session.owner_user_id != owner_id
            or session.id == current_session_id):
        return None
    before, after = max(0, min(before, MAX_SIDE)), max(0, min(after, MAX_SIDE))
    rows = list(db.scalars(select(MessageRecord).where(
        MessageRecord.session_id == session_id, MessageRecord.role.in_(ROLES),
        MessageRecord.sequence >= around - before * 4, MessageRecord.sequence <= around + after * 4)
        .order_by(MessageRecord.sequence)))
    earlier = [m for m in rows if m.sequence < around][-before:] if before else []
    later = [m for m in rows if m.sequence >= around][:after + 1]
    messages = _visible(db, earlier + later)
    out, used = [], 0
    for message in messages:
        content = message.content[:MESSAGE_CHARS]
        if used + len(content) > PAGE_CHARS:
            break
        used += len(content)
        out.append({'sequence': message.sequence, 'role': message.role, 'content': content})
    audit(db, tenant_id, owner_id, 'conversation.read', 'session', str(session_id), {'messages': len(out)})
    return {'session_id': str(session_id), 'session_title': session.title, 'messages': out}


def _snippet(content: str, tokens: list[str]) -> str:
    lowered = content.casefold()
    position = min((lowered.find(token) for token in tokens if token in lowered), default=-1)
    start = max(0, position - SNIPPET_CHARS // 4) if position > 0 else 0
    window = content[start:start + SNIPPET_CHARS].replace('\n', ' ')
    return ('…' if start else '') + window
