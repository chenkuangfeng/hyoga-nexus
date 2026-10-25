"""Vendor-neutral store contracts; no SDK, database or platform imports."""
from __future__ import annotations
from typing import Protocol
from .models import ModelMessage
from .budgets import RuntimeProgress


class RuntimeStorePort(Protocol):
    """Persist runtime observations and progress through an implementation-owned transaction.

    Successful return means the implementation accepted the write; adapters own durability."""
    async def emit(self, kind: str, payload: dict[str, object]) -> None: ...
    async def message(self, message: ModelMessage) -> None: ...
    async def save_progress(self, progress: RuntimeProgress) -> None: ...
