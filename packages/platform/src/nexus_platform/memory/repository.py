"""SQLAlchemy adapter for `nexus_memory.ports.MemoryRepository`.

Every method runs in the caller's transaction and does not commit. Row locks use
`with_for_update()` where the port asks for them. Audit records are written through
`authz.audit`, the same path other platform services use.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus_core.platform import new_id, utc_now
from nexus_memory.ports import DraftView, EntryView, VersionView
from nexus_platform.authz.audit import audit
from nexus_platform.persistence.models import (
    MemoryDraftRecord,
    MemoryEntryRecord,
    MemoryVersionRecord,
    RunRecord,
)


class SqlMemoryRepository:
    """Bind the memory port to one open SQLAlchemy session."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def published_entries(self, tenant_id: UUID, owner_id: UUID, project: str) -> list[EntryView]:
        query = select(MemoryEntryRecord).where(
            MemoryEntryRecord.tenant_id == tenant_id,
            MemoryEntryRecord.owner_user_id == owner_id,
            MemoryEntryRecord.active.is_(True),
        )
        if project:
            query = query.where(MemoryEntryRecord.project.in_(['', project]))
        return [_entry(row) for row in self.db.scalars(query.order_by(MemoryEntryRecord.title))]

    def pending_drafts(self, tenant_id: UUID, owner_id: UUID) -> list[DraftView]:
        query = (
            select(MemoryDraftRecord, RunRecord.principal_id)
            .join(RunRecord, RunRecord.id == MemoryDraftRecord.source_run_id)
            .where(
                MemoryDraftRecord.tenant_id == tenant_id,
                RunRecord.principal_id == owner_id,
                MemoryDraftRecord.status == 'pending_review',
            )
            .order_by(MemoryDraftRecord.created_at)
        )
        return [_draft(row, owner) for row, owner in self.db.execute(query).all()]

    def owned_entry(self, tenant_id: UUID, owner_id: UUID, entry_id: UUID, *, lock: bool = False) -> EntryView | None:
        query = select(MemoryEntryRecord).where(
            MemoryEntryRecord.id == entry_id,
            MemoryEntryRecord.tenant_id == tenant_id,
            MemoryEntryRecord.owner_user_id == owner_id,
            MemoryEntryRecord.active.is_(True),
        )
        if lock:
            query = query.with_for_update()
        row = self.db.scalar(query)
        return _entry(row) if row else None

    def version(self, entry_id: UUID, version: int) -> VersionView | None:
        row = self.db.get(MemoryVersionRecord, (entry_id, version))
        return _version(row) if row else None

    def draft_for_review(self, tenant_id: UUID, draft_id: UUID) -> DraftView | None:
        row = self.db.scalar(
            select(MemoryDraftRecord).where(MemoryDraftRecord.id == draft_id).with_for_update()
        )
        if row is None or row.tenant_id != tenant_id:
            return None
        run = self.db.get(RunRecord, row.source_run_id)
        if run is None:
            return None
        return _draft(row, run.principal_id)

    def set_draft_status(self, draft_id: UUID, status: str) -> None:
        self.db.get(MemoryDraftRecord, draft_id).status = status

    def create_entry(self, *, tenant_id: UUID, owner_id: UUID, kind: str, title: str, project: str) -> EntryView:
        row = MemoryEntryRecord(
            id=new_id(), tenant_id=tenant_id, owner_user_id=owner_id, kind=kind, title=title,
            project=project, active=True, current_version=1, created_at=utc_now(),
        )
        self.db.add(row)
        self.db.flush()
        return _entry(row)

    def bump_entry(self, entry_id: UUID, *, current_version: int, title: str | None = None,
                   project: str | None = None, active: bool | None = None) -> None:
        row = self.db.get(MemoryEntryRecord, entry_id)
        row.current_version = current_version
        if title is not None:
            row.title = title
        if project is not None:
            row.project = project
        if active is not None:
            row.active = active

    def append_version(self, *, entry_id: UUID, version: int, content: str, source_run_id: UUID,
                       source_draft_id: UUID | None, reviewer_id: UUID | None) -> None:
        self.db.add(MemoryVersionRecord(
            entry_id=entry_id, version=version, content=content, source_run_id=source_run_id,
            source_draft_id=source_draft_id, reviewed_by=reviewer_id, created_at=utc_now(),
        ))

    def audit(self, tenant_id: UUID, actor_id: UUID, action: str, target_type: str,
              target_id: str, metadata: dict[str, Any] | None = None) -> None:
        audit(self.db, tenant_id, actor_id, action, target_type, target_id, metadata)


def _entry(row: MemoryEntryRecord) -> EntryView:
    return EntryView(
        id=row.id, tenant_id=row.tenant_id, owner_user_id=row.owner_user_id, kind=row.kind,
        title=row.title, project=row.project, active=row.active, current_version=row.current_version,
    )


def _version(row: MemoryVersionRecord) -> VersionView:
    return VersionView(
        entry_id=row.entry_id, version=row.version, content=row.content,
        source_run_id=row.source_run_id, source_draft_id=row.source_draft_id,
    )


def _draft(row: MemoryDraftRecord, owner_id: UUID) -> DraftView:
    return DraftView(
        id=row.id, tenant_id=row.tenant_id, owner_user_id=owner_id, kind=row.kind,
        diff=row.diff, status=row.status, source_run_id=row.source_run_id,
    )
