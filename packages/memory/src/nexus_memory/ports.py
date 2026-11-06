"""Storage port and value types used by the memory rules.

Contract notes:
- Every read in `MemoryRepository` is scoped by tenant and, where stated, by owner.
  Implementations must not return foreign or archived entries from owner-scoped methods;
  the service maps a missing result to `MemoryNotFound` with one message so absent,
  foreign and archived items are indistinguishable to callers.
- Writes do not commit. The caller's transaction decides whether they persist.
- `*_for_update` / `lock=True` methods must take a row lock so that concurrent reviews
  of the same draft or entry serialize.
- Timestamps passed in or returned are timezone-aware UTC. Implementations convert before
  storing and before comparing, because SQLite does not keep timezone offsets.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID


class MemoryNotFound(LookupError):
    """Requested memory item is absent, foreign, archived, or not reviewable by the caller."""


class MemoryConflict(Exception):
    """Optimistic version check failed, the draft was already reviewed, or the budget would be exceeded."""


class _Unset:
    """Sentinel for optional updates where `None` is a meaningful value (for example, clearing `valid_until`)."""
    def __repr__(self) -> str:
        return 'UNSET'


UNSET: Any = _Unset()


@dataclass(frozen=True)
class EntryView:
    """A published memory entry (fact or SOP) as the rules see it."""
    id: UUID
    tenant_id: UUID
    owner_user_id: UUID
    kind: str
    title: str
    project: str
    active: bool
    current_version: int
    enabled: bool = True
    valid_until: datetime | None = None
    #: Label the entry is about; two entries with the same `text.topic_key` are the same subject.
    topic: str = ''
    #: 1 (trivial) to 5 (essential); copied from the draft on publish, editable by the owner.
    importance: int = 3


@dataclass(frozen=True)
class VersionView:
    """One immutable published version with its provenance."""
    entry_id: UUID
    version: int
    content: str
    source_run_id: UUID
    source_draft_id: UUID | None
    fingerprint: str = ''
    source_message_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class DraftView:
    """A proposed memory change; `owner_user_id` is the principal of the run that proposed it."""
    id: UUID
    tenant_id: UUID
    owner_user_id: UUID
    kind: str
    diff: str
    status: str
    source_run_id: UUID
    fingerprint: str = ''
    base_version: int | None = None
    origin: str = 'foreground'
    source_message_ids: tuple[str, ...] = ()
    #: Extraction metadata (openspec 2026-11-06-memory-evolution stage 1). All optional: foreground
    #: proposals may omit them, and drafts created before the stage have none.
    topic: str = ''
    importance: int | None = None
    confidence: str | None = None
    valid_until: datetime | None = None
    #: `({'message_id', 'quote'}, ...)`: user words the draft was taken from, checked at extraction.
    evidence: tuple[dict[str, Any], ...] = ()
    #: Review hints with fixed keys (`conflict`, `similar`); never change what is published.
    annotations: dict[str, Any] = field(default_factory=dict)
    #: Entry an edit draft updates. Set when the draft was proposed against an entry, so the reviewer
    #: does not have to pick it; `base_version` is that entry's version at proposal time.
    target_entry_id: UUID | None = None


@dataclass(frozen=True)
class DraftMeta:
    """Optional metadata stored with a new draft; see `DraftView` for the meaning of each field."""
    topic: str = ''
    importance: int | None = None
    confidence: str | None = None
    valid_until: datetime | None = None
    evidence: tuple[dict[str, Any], ...] = ()
    annotations: dict[str, Any] = field(default_factory=dict)
    target_entry_id: UUID | None = None


@dataclass(frozen=True)
class LiveEntry:
    """An active entry with its current content, for topic matching and overlap checks."""
    entry: EntryView
    content: str


@dataclass(frozen=True)
class SearchRow:
    """One candidate from the keyword channel. `score` is higher-is-better and relative to nothing yet."""
    entry_id: UUID
    title: str
    kind: str
    version: int
    content: str
    score: float


@dataclass(frozen=True)
class SizedEntry:
    """Active entry and the character count of its current content, for budget accounting."""
    id: UUID
    title: str
    chars: int


class MemoryRepository(Protocol):
    """Persistence operations required by the memory rules."""

    def published_entries(self, tenant_id: UUID, owner_id: UUID, project: str) -> list[EntryView]:
        """Active entries of the owner (enabled or not), ordered by title. Empty `project` means no project
        filter; otherwise entries with project '' (global) or equal to `project` are returned."""

    def pending_drafts(self, tenant_id: UUID, owner_id: UUID) -> list[DraftView]:
        """Drafts awaiting review whose source run belongs to `owner_id`, oldest first."""

    def owned_entry(self, tenant_id: UUID, owner_id: UUID, entry_id: UUID, *, lock: bool = False) -> EntryView | None:
        """Active entry owned by `owner_id` in `tenant_id`, or None. `lock=True` takes a row lock."""

    def version(self, entry_id: UUID, version: int) -> VersionView | None:
        """Return a specific version of an entry, or None."""

    def draft_for_review(self, tenant_id: UUID, draft_id: UUID) -> DraftView | None:
        """Draft in `tenant_id` with its source owner, row-locked; None if absent."""

    def set_draft_status(self, draft_id: UUID, status: str) -> None: ...

    def create_draft(self, *, tenant_id: UUID, source_run_id: UUID, kind: str, diff: str, fingerprint: str,
                     base_version: int | None, origin: str, source_message_ids: tuple[str, ...],
                     meta: DraftMeta | None = None) -> UUID:
        """Insert a pending draft. The owner is the principal of `source_run_id`. `meta` defaults to empty."""

    def find_duplicate(self, tenant_id: UUID, owner_id: UUID, fingerprint: str) -> tuple[str, UUID] | None:
        """(`entry` | `draft`, id) of a current published version or pending draft with this fingerprint."""

    def is_tombstoned(self, tenant_id: UUID, owner_id: UUID, fingerprint: str) -> bool:
        """True when this content was rejected before and must not be proposed again by the owner."""

    def add_tombstone(self, tenant_id: UUID, owner_id: UUID, fingerprint: str, topic: str = '') -> None:
        """Record rejected content. A repeated fingerprint keeps one row and takes the newer topic."""

    def rejected_topics(self, tenant_id: UUID, owner_id: UUID, since: datetime, limit: int) -> list[str]:
        """Non-empty tombstone topics created at or after `since`, newest first, without duplicates."""

    def live_entries(self, tenant_id: UUID, owner_id: UUID) -> list[LiveEntry]:
        """Active entries (enabled or not) with their current content, most recently updated first."""

    def sized_entries(self, tenant_id: UUID, owner_id: UUID) -> list[SizedEntry]:
        """Active entries with the character count of their current version."""

    def create_entry(self, *, tenant_id: UUID, owner_id: UUID, kind: str, title: str, project: str,
                     topic: str = '', importance: int = 3) -> EntryView:
        """Create an active entry at version 1 (the caller appends that version)."""

    def bump_entry(self, entry_id: UUID, *, current_version: int, title: str | None = None,
                   project: str | None = None, active: bool | None = None,
                   enabled: bool | None = None, valid_until: Any = UNSET,
                   topic: str | None = None, importance: int | None = None) -> None:
        """Set the entry's current version and any provided header fields. `UNSET` leaves `valid_until` as is."""

    def append_version(self, *, entry_id: UUID, version: int, content: str, source_run_id: UUID,
                       source_draft_id: UUID | None, reviewer_id: UUID | None, fingerprint: str,
                       source_message_ids: tuple[str, ...]) -> None:
        """Append an immutable version and update the keyword index in the same transaction."""

    def search(self, tenant_id: UUID, owner_id: UUID, tokens: list[str], now: datetime, limit: int) -> list[SearchRow]:
        """Keyword candidates within the owner's enabled, active, unexpired current versions. Every token must match."""

    def audit(self, tenant_id: UUID, actor_id: UUID, action: str, target_type: str,
              target_id: str, metadata: dict[str, Any] | None = None) -> None: ...
