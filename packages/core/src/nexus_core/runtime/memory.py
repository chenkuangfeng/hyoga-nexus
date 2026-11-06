"""Vendor-neutral memory contracts; no SDK, database or platform imports."""
from __future__ import annotations
from typing import Literal, Protocol


class MemoryDraftPort(Protocol):
    """Propose a memory change for review; this operation does not publish long-term memory."""
    async def propose(self, kind: Literal['memory', 'sop'], scope: str, diff: str, *,
                      entry_id: str | None = None, base_version: int | None = None,
                      topic: str = '', importance: int | None = None, valid_until: str | None = None) -> str:
        """Create a pending draft and return a short outcome line for the model.

        `topic` names the subject (a draft whose topic matches a published entry becomes an edit of it),
        `importance` is 1-5, and `valid_until` is an optional `YYYY-MM-DD` end date for time-bound notes.
        """
        ...
