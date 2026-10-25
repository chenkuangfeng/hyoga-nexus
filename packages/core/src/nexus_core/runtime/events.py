"""Vendor-neutral events contracts; no SDK, database or platform imports."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class LifecycleEvent:
    """Lifecycle phase with Run correlation, turn and optional tool/error classification."""
    run_id: str
    phase: str
    turn: int = 0
    tool_name: str | None = None
    error_code: str | None = None


class RuntimeLifecycleHook(Protocol):
    """Observe lifecycle events asynchronously without implicitly gaining resource access."""
    async def __call__(self, event: LifecycleEvent) -> None: ...
