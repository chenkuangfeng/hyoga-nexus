"""Memory data retention (openspec 2026-11-06-memory-evolution stage 3, C3).

The worker calls `run_retention` at most once an hour. It deletes data that only explains past work and
is never read by the rules again:

| Data | Kept for | Action |
| --- | --- | --- |
| rejected drafts (`memory_drafts.status='rejected'`) | 30 days | delete; the tombstone stays |
| finished capture jobs (`completed` / `failed`) | 14 days | delete |

Audit records, published versions, approved drafts and tombstones are kept forever. Each kind deletes at
most `max_rows` rows per call so a backlog never holds a long lock. No per-row audit is written: the
deleted rows are themselves the noise this pass removes (octop-memory ADR-028); counts are logged.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from nexus_core.platform import utc_now
from nexus_platform.persistence.models import MemoryCaptureJobRecord, MemoryDraftRecord

logger = logging.getLogger(__name__)

REJECTED_DRAFT_RETENTION = timedelta(days=30)
FINISHED_JOB_RETENTION = timedelta(days=14)
MAX_ROWS = 500


def run_retention(db: Session, *, now: datetime | None = None, max_rows: int = MAX_ROWS) -> dict[str, int]:
    """Delete expired rows inside the caller's transaction; returns how many of each kind were removed."""
    now = now or utc_now()
    drafts = list(db.scalars(select(MemoryDraftRecord.id).where(
        MemoryDraftRecord.status == 'rejected',
        MemoryDraftRecord.created_at < now - REJECTED_DRAFT_RETENTION).limit(max_rows)))
    if drafts:
        db.execute(delete(MemoryDraftRecord).where(MemoryDraftRecord.id.in_(drafts)))
    jobs = list(db.scalars(select(MemoryCaptureJobRecord.id).where(
        MemoryCaptureJobRecord.state.in_(('completed', 'failed')),
        func.coalesce(MemoryCaptureJobRecord.completed_at, MemoryCaptureJobRecord.created_at)
        < now - FINISHED_JOB_RETENTION).limit(max_rows)))
    if jobs:
        db.execute(delete(MemoryCaptureJobRecord).where(MemoryCaptureJobRecord.id.in_(jobs)))
    counts = {'rejected_drafts': len(drafts), 'capture_jobs': len(jobs)}
    if drafts or jobs:
        logger.info('memory retention removed rows', extra=counts)
    return counts
