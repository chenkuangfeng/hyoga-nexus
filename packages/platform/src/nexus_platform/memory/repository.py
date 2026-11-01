"""SQLAlchemy adapter for `nexus_memory.ports.MemoryRepository`.

Every method runs in the caller's transaction and does not commit. Row locks use
`with_for_update()` where the port asks for them. Audit records are written through
`authz.audit`, the same path other platform services use.

Keyword search has two paths with the same semantics (every query token must match):
- SQLite with the `memory_fts` FTS5 table: `MATCH` on the index, joined to live current versions.
- Any database: substring match on the stored tokens, which is portable and used when FTS5 is absent.
Single CJK characters are never bigram tokens, so both paths match them against the content.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, bindparam, func, literal, select, text
from sqlalchemy import Uuid as SqlUuid
from sqlalchemy.orm import Session

from nexus_core.platform import new_id, utc_now
from nexus_memory import text as memtext
from nexus_memory.ports import UNSET, DraftView, EntryView, SearchRow, SizedEntry, VersionView
from nexus_platform.authz.audit import audit
from nexus_platform.persistence.models import (
    MemoryDraftRecord,
    MemoryEntryRecord,
    MemoryTombstoneRecord,
    MemoryVersionRecord,
    RunRecord,
)


class SqlMemoryRepository:
    """Bind the memory port to one open SQLAlchemy session."""

    def __init__(self, db: Session) -> None:
        self.db = db

    # --- reads -------------------------------------------------------------

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

    def find_duplicate(self, tenant_id: UUID, owner_id: UUID, fingerprint: str) -> tuple[str, UUID] | None:
        entry = self.db.scalar(
            select(MemoryEntryRecord.id)
            .join(MemoryVersionRecord, (MemoryVersionRecord.entry_id == MemoryEntryRecord.id)
                  & (MemoryVersionRecord.version == MemoryEntryRecord.current_version))
            .where(MemoryEntryRecord.tenant_id == tenant_id, MemoryEntryRecord.owner_user_id == owner_id,
                   MemoryEntryRecord.active.is_(True), MemoryVersionRecord.fingerprint == fingerprint)
            .limit(1)
        )
        if entry is not None:
            return ('entry', entry)
        draft = self.db.scalar(
            select(MemoryDraftRecord.id)
            .join(RunRecord, RunRecord.id == MemoryDraftRecord.source_run_id)
            .where(MemoryDraftRecord.tenant_id == tenant_id, RunRecord.principal_id == owner_id,
                   MemoryDraftRecord.status == 'pending_review', MemoryDraftRecord.fingerprint == fingerprint)
            .limit(1)
        )
        return ('draft', draft) if draft is not None else None

    def is_tombstoned(self, tenant_id: UUID, owner_id: UUID, fingerprint: str) -> bool:
        return self.db.get(MemoryTombstoneRecord, (tenant_id, owner_id, fingerprint)) is not None

    def sized_entries(self, tenant_id: UUID, owner_id: UUID) -> list[SizedEntry]:
        rows = self.db.execute(
            select(MemoryEntryRecord.id, MemoryEntryRecord.title, func.length(MemoryVersionRecord.content))
            .join(MemoryVersionRecord, (MemoryVersionRecord.entry_id == MemoryEntryRecord.id)
                  & (MemoryVersionRecord.version == MemoryEntryRecord.current_version))
            .where(MemoryEntryRecord.tenant_id == tenant_id, MemoryEntryRecord.owner_user_id == owner_id,
                   MemoryEntryRecord.active.is_(True))
            .order_by(MemoryEntryRecord.title)
        ).all()
        return [SizedEntry(id=entry_id, title=title, chars=int(chars or 0)) for entry_id, title, chars in rows]

    def search(self, tenant_id: UUID, owner_id: UUID, tokens: list[str], now: datetime, limit: int) -> list[SearchRow]:
        multi = [t for t in tokens if not memtext.is_single_cjk(t)]
        singles = [t for t in tokens if memtext.is_single_cjk(t)]
        if multi and self._fts_available():
            return self._search_fts(tenant_id, owner_id, multi, singles, now, limit)
        if multi and self.db.get_bind().dialect.name == 'sqlite':
            # SQLite without the FTS5 table: results are still correct but substring-based. Record the
            # degradation so operators can see that the keyword index is not in use.
            self.audit(tenant_id, owner_id, 'memory.search_degraded', 'memory', '', {'reason': 'fts5_unavailable'})
        return self._search_like(tenant_id, owner_id, tokens, now, limit)

    # --- writes ------------------------------------------------------------

    def create_draft(self, *, tenant_id: UUID, source_run_id: UUID, kind: str, diff: str, fingerprint: str,
                     base_version: int | None, origin: str, source_message_ids: tuple[str, ...]) -> UUID:
        run = self.db.get(RunRecord, source_run_id)
        row = MemoryDraftRecord(
            id=new_id(), tenant_id=tenant_id, source_run_id=source_run_id, kind=kind,
            scope=str(run.session_id), diff=diff, status='pending_review', created_at=utc_now(),
            origin=origin, fingerprint=fingerprint, base_version=base_version,
            source_message_ids=list(source_message_ids),
        )
        self.db.add(row)
        self.db.flush()
        return row.id

    def set_draft_status(self, draft_id: UUID, status: str) -> None:
        self.db.get(MemoryDraftRecord, draft_id).status = status

    def add_tombstone(self, tenant_id: UUID, owner_id: UUID, fingerprint: str) -> None:
        if self.db.get(MemoryTombstoneRecord, (tenant_id, owner_id, fingerprint)) is None:
            self.db.add(MemoryTombstoneRecord(tenant_id=tenant_id, owner_user_id=owner_id,
                                              fingerprint=fingerprint, created_at=utc_now()))

    def create_entry(self, *, tenant_id: UUID, owner_id: UUID, kind: str, title: str, project: str) -> EntryView:
        row = MemoryEntryRecord(
            id=new_id(), tenant_id=tenant_id, owner_user_id=owner_id, kind=kind, title=title,
            project=project, active=True, current_version=1, created_at=utc_now(), enabled=True,
        )
        self.db.add(row)
        self.db.flush()
        return _entry(row)

    def bump_entry(self, entry_id: UUID, *, current_version: int, title: str | None = None,
                   project: str | None = None, active: bool | None = None,
                   enabled: bool | None = None, valid_until: Any = UNSET) -> None:
        row = self.db.get(MemoryEntryRecord, entry_id)
        row.current_version = current_version
        if title is not None:
            row.title = title
        if project is not None:
            row.project = project
        if active is not None:
            row.active = active
        if enabled is not None:
            row.enabled = enabled
        if valid_until is not UNSET:
            row.valid_until = valid_until

    def append_version(self, *, entry_id: UUID, version: int, content: str, source_run_id: UUID,
                       source_draft_id: UUID | None, reviewer_id: UUID | None, fingerprint: str,
                       source_message_ids: tuple[str, ...]) -> None:
        search_id = self.db.scalar(select(func.coalesce(func.max(MemoryVersionRecord.search_id), 0))) + 1
        self.db.add(MemoryVersionRecord(
            entry_id=entry_id, version=version, content=content, source_run_id=source_run_id,
            source_draft_id=source_draft_id, reviewed_by=reviewer_id, created_at=utc_now(),
            fingerprint=fingerprint, tokens=memtext.tokenize(content), search_id=search_id,
            source_message_ids=list(source_message_ids),
        ))
        self.db.flush()
        if self._fts_available():
            # Only the current version of an entry stays in the index; older rows are removed in this
            # transaction. Archived or disabled entries keep their rows and are filtered at query time.
            self.db.execute(text(
                'DELETE FROM memory_fts WHERE rowid IN ('
                ' SELECT search_id FROM memory_versions WHERE entry_id = :entry AND search_id IS NOT NULL'
                ' AND search_id <> :current)'
            ), {'entry': _bind_uuid(entry_id), 'current': search_id})
            self.db.execute(text('INSERT INTO memory_fts(rowid, tokens) VALUES (:sid, :tokens)'),
                            {'sid': search_id, 'tokens': memtext.tokenize(content)})

    def audit(self, tenant_id: UUID, actor_id: UUID, action: str, target_type: str,
              target_id: str, metadata: dict[str, Any] | None = None) -> None:
        audit(self.db, tenant_id, actor_id, action, target_type, target_id, metadata)

    # --- keyword search internals -------------------------------------------

    def _fts_available(self) -> bool:
        if self.db.get_bind().dialect.name != 'sqlite':
            return False
        return self.db.execute(text(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'memory_fts'")).first() is not None

    def _search_fts(self, tenant_id: UUID, owner_id: UUID, multi: list[str], singles: list[str],
                    now: datetime, limit: int) -> list[SearchRow]:
        match = ' AND '.join('"' + token.replace('"', '""') + '"' for token in multi)
        clauses = ['v.version = e.current_version', 'e.tenant_id = :tenant', 'e.owner_user_id = :owner',
                   'e.active = 1', 'e.enabled = 1', '(e.valid_until IS NULL OR e.valid_until > :now)']
        params: dict[str, Any] = {'match': match, 'tenant': tenant_id, 'owner': owner_id, 'now': now.replace(tzinfo=None),
                                  'limit': limit}
        for index, char in enumerate(singles):
            clauses.append(f'v.content LIKE :single{index} ESCAPE \'\\\'')
            params[f'single{index}'] = '%' + _like_escape(char) + '%'
        sql = text(
            'SELECT e.id AS entry_id, e.title AS title, e.kind AS kind, v.version AS version,'
            ' v.content AS content, -bm25(memory_fts) AS score'
            ' FROM memory_fts'
            ' JOIN memory_versions v ON v.search_id = memory_fts.rowid'
            ' JOIN memory_entries e ON e.id = v.entry_id'
            ' WHERE memory_fts MATCH :match AND ' + ' AND '.join(clauses) +
            ' ORDER BY score DESC LIMIT :limit'
        ).bindparams(bindparam('tenant', type_=SqlUuid(as_uuid=True)),
                     bindparam('owner', type_=SqlUuid(as_uuid=True)),
                     bindparam('now', type_=DateTime()))
        rows = self.db.execute(sql, params).all()
        return [SearchRow(entry_id=_as_uuid(r.entry_id), title=r.title, kind=r.kind, version=r.version,
                          content=r.content, score=float(r.score)) for r in rows]

    def _search_like(self, tenant_id: UUID, owner_id: UUID, tokens: list[str], now: datetime,
                     limit: int) -> list[SearchRow]:
        query = (
            select(MemoryEntryRecord.id, MemoryEntryRecord.title, MemoryEntryRecord.kind,
                   MemoryVersionRecord.version, MemoryVersionRecord.content, MemoryVersionRecord.created_at)
            .join(MemoryVersionRecord, (MemoryVersionRecord.entry_id == MemoryEntryRecord.id)
                  & (MemoryVersionRecord.version == MemoryEntryRecord.current_version))
            .where(
                MemoryEntryRecord.tenant_id == tenant_id,
                MemoryEntryRecord.owner_user_id == owner_id,
                MemoryEntryRecord.active.is_(True),
                MemoryEntryRecord.enabled.is_(True),
                (MemoryEntryRecord.valid_until.is_(None)) | (MemoryEntryRecord.valid_until > now),
            )
        )
        for token in tokens:
            if memtext.is_single_cjk(token):
                query = query.where(MemoryVersionRecord.content.contains(token, autoescape=True))
            else:
                haystack = literal(' ') + MemoryVersionRecord.tokens + literal(' ')
                query = query.where(haystack.contains(f' {token} ', autoescape=True))
        rows = self.db.execute(query.order_by(MemoryVersionRecord.created_at.desc()).limit(limit)).all()
        return [SearchRow(entry_id=row.id, title=row.title, kind=row.kind, version=row.version,
                          content=row.content, score=1.0) for row in rows]


def _like_escape(value: str) -> str:
    return value.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')


def _bind_uuid(value: UUID) -> Any:
    return value.hex if hasattr(value, 'hex') else value


def _as_uuid(value: Any) -> UUID:
    return value if isinstance(value, UUID) else UUID(str(value))


def _aware(value: datetime | None) -> datetime | None:
    """SQLite returns naive datetimes; the rules require aware UTC, and stored values are UTC."""
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=UTC)


def _entry(row: MemoryEntryRecord) -> EntryView:
    return EntryView(
        id=row.id, tenant_id=row.tenant_id, owner_user_id=row.owner_user_id, kind=row.kind,
        title=row.title, project=row.project, active=row.active, current_version=row.current_version,
        enabled=bool(row.enabled), valid_until=_aware(row.valid_until),
    )


def _version(row: MemoryVersionRecord) -> VersionView:
    return VersionView(
        entry_id=row.entry_id, version=row.version, content=row.content,
        source_run_id=row.source_run_id, source_draft_id=row.source_draft_id,
        fingerprint=row.fingerprint or '', source_message_ids=tuple(row.source_message_ids or ()),
    )


def _draft(row: MemoryDraftRecord, owner_id: UUID) -> DraftView:
    return DraftView(
        id=row.id, tenant_id=row.tenant_id, owner_user_id=owner_id, kind=row.kind,
        diff=row.diff, status=row.status, source_run_id=row.source_run_id,
        fingerprint=row.fingerprint or '', base_version=row.base_version, origin=row.origin,
        source_message_ids=tuple(row.source_message_ids or ()),
    )
