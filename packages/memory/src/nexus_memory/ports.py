"""Storage port and value types used by the memory rules.

Contract notes:
- Every read in `MemoryRepository` is scoped by workspace and, where stated, by owner.
  Implementations must not return foreign or archived entries from owner-scoped methods;
  the service maps a missing result to `MemoryNotFound` with one message so absent,
  foreign and archived items are indistinguishable to callers.
- Writes do not commit. The caller's transaction decides whether they persist.
- `*_for_update` / `lock=True` methods must take a row lock so that concurrent reviews
  of the same draft or entry serialize.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID


class MemoryNotFound(LookupError):
    """Requested memory item is absent, foreign, archived, or not reviewable by the caller."""


class MemoryConflict(Exception):
    """Optimistic version check failed, or the draft was already reviewed."""


@dataclass(frozen=True)
class EntryView:
    """A published memory entry (fact or SOP) as the rules see it."""
    id: UUID
    workspace_id: UUID
    owner_user_id: UUID
    kind: str
    title: str
    project: str
    active: bool
    current_version: int


@dataclass(frozen=True)
class VersionView:
    """One immutable published version with its provenance."""
    entry_id: UUID
    version: int
    content: str
    source_run_id: UUID
    source_draft_id: UUID | None


@dataclass(frozen=True)
class DraftView:
    """A proposed memory change; `owner_user_id` is the principal of the run that proposed it."""
    id: UUID
    workspace_id: UUID
    owner_user_id: UUID
    kind: str
    diff: str
    status: str
    source_run_id: UUID


class MemoryRepository(Protocol):
    """Persistence operations required by the memory rules."""

    def published_entries(self, workspace_id: UUID, owner_id: UUID, project: str) -> list[EntryView]:
        """Active entries of the owner, ordered by title. Empty `project` means no project filter;
        otherwise entries with project '' (global) or equal to `project` are returned."""

    def pending_drafts(self, workspace_id: UUID, owner_id: UUID) -> list[DraftView]:
        """Drafts awaiting review whose source run belongs to `owner_id`, oldest first."""

    def owned_entry(self, workspace_id: UUID, owner_id: UUID, entry_id: UUID, *, lock: bool = False) -> EntryView | None:
        """Active entry owned by `owner_id` in `workspace_id`, or None. `lock=True` takes a row lock."""

    def version(self, entry_id: UUID, version: int) -> VersionView | None:
        """Return a specific version of an entry, or None."""

    def draft_for_review(self, workspace_id: UUID, draft_id: UUID) -> DraftView | None:
        """Draft in `workspace_id` with its source owner, row-locked; None if absent."""

    def set_draft_status(self, draft_id: UUID, status: str) -> None: ...

    def create_entry(self, *, workspace_id: UUID, owner_id: UUID, kind: str, title: str, project: str) -> EntryView:
        """Create an active entry at version 1 (the caller appends that version)."""

    def bump_entry(self, entry_id: UUID, *, current_version: int, title: str | None = None,
                   project: str | None = None, active: bool | None = None) -> None:
        """Set the entry's current version and any provided header fields."""

    def append_version(self, *, entry_id: UUID, version: int, content: str, source_run_id: UUID,
                       source_draft_id: UUID | None, reviewer_id: UUID | None) -> None: ...

    def audit(self, workspace_id: UUID, actor_id: UUID, action: str, target_type: str,
              target_id: str, metadata: dict[str, Any] | None = None) -> None: ...
