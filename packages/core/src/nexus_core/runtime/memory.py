"""Vendor-neutral memory contracts; no SDK, database or platform imports."""
from __future__ import annotations
from typing import Literal, Protocol


class MemoryDraftPort(Protocol):
    """Propose a memory change for review; this operation does not publish long-term memory."""
    async def propose(self, kind: Literal['memory', 'sop'], scope: str, diff: str) -> str: ...
