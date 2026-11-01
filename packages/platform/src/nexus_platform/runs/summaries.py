"""Append-only context summary chain (openspec 2026-11-01-context-token-performance, P11).

Rows are inserted, never updated. A new summary names the one it replaces in `supersedes_id`, and
the effective summary is the row with the largest `through_sequence` that no row supersedes. The cut
point only moves forward: a summary that does not extend the current one is not written.
"""
from __future__ import annotations
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus_core.platform import new_id, utc_now
from nexus_platform.persistence.models import ContextSummaryRecord

#: Summaries longer than this are truncated before storage; the model input budget is bounded separately.
MAX_SUMMARY_CHARS = 8000


def _superseded(session_id: UUID):
    """Subquery of identifiers replaced by a later row. NULLs are excluded so NOT IN stays well-defined."""
    return select(ContextSummaryRecord.supersedes_id).where(
        ContextSummaryRecord.session_id == session_id, ContextSummaryRecord.supersedes_id.is_not(None))


def effective_summary(db: Session, session_id: UUID) -> ContextSummaryRecord | None:
    """Return the unsuperseded row with the furthest cut point, or None when the session has no summary."""
    return db.scalar(
        select(ContextSummaryRecord)
        .where(ContextSummaryRecord.session_id == session_id,
               ContextSummaryRecord.id.not_in(_superseded(session_id)))
        .order_by(ContextSummaryRecord.through_sequence.desc(), ContextSummaryRecord.created_at.desc())
        .limit(1))


def append_summary(db: Session, *, session_id: UUID, tenant_id: UUID, source_run_id: UUID,
                   through_sequence: int, content: str, max_chars: int = MAX_SUMMARY_CHARS) -> ContextSummaryRecord | None:
    """Insert a summary that extends the effective cut point; return None when it does not move forward."""
    current = effective_summary(db, session_id)
    if current is not None and through_sequence <= current.through_sequence:
        return None
    record = ContextSummaryRecord(
        id=new_id(), session_id=session_id, tenant_id=tenant_id, source_run_id=source_run_id,
        through_sequence=through_sequence, content=content[:max_chars],
        supersedes_id=current.id if current is not None else None, created_at=utc_now())
    db.add(record)
    return record
