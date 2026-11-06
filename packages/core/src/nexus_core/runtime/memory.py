"""Vendor-neutral memory contracts; no SDK, database or platform imports."""
from __future__ import annotations
from typing import Literal, Protocol


class MemoryDraftPort(Protocol):
    """Propose a memory change for review; this operation does not publish long-term memory."""
    async def propose(self, kind: Literal['memory', 'sop', 'profile'], scope: str, diff: str, *,
                      entry_id: str | None = None, base_version: int | None = None,
                      topic: str = '', importance: int | None = None, valid_until: str | None = None) -> str:
        """Create a pending draft and return a short outcome line for the model.

        `topic` names the subject (a draft whose topic matches a published entry becomes an edit of it),
        `importance` is 1-5, and `valid_until` is an optional `YYYY-MM-DD` end date for time-bound notes.
        """
        ...


class MemoryProviderContext(Protocol):
    """What a memory provider may know and do for one call (openspec 2026-11-06-memory-evolution D6).

    `propose` is the provider's only way to write: it creates a pending draft for the owner to review
    and returns a short outcome line. Providers never publish memory.
    """
    tenant_id: str
    owner_id: str
    session_id: str

    def propose(self, kind: str, diff: str, *, topic: str = '') -> str: ...


class MemoryProviderPort(Protocol):
    """An external long-term memory backend (hermes-agent `MemoryProvider`), at most one per space.

    Hooks are synchronous and called with a deadline; a provider that is slow or failing is skipped,
    never allowed to fail a Run. Returned text is fenced and escaped by the platform as user data.
    """
    name: str

    def snapshot_block(self, ctx: MemoryProviderContext) -> str:
        """Extra text frozen into a new session's memory snapshot ('' for none)."""
        ...

    def prefetch(self, ctx: MemoryProviderContext, query: str) -> str:
        """Extra material for this turn's question ('' for none)."""
        ...

    def sync_turn(self, ctx: MemoryProviderContext, user: str, assistant: str) -> None:
        """Observe a finished turn (runs in the background after the Run completes)."""
        ...
