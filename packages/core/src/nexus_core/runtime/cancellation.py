"""Vendor-neutral cancellation contracts; no SDK, database or platform imports."""
from __future__ import annotations
from typing import Protocol


class CancellationTokenPort(Protocol):
    """Expose a cooperative cancellation signal to model and tool adapters."""
    async def wait(self) -> None: ...
    def check(self) -> None: ...
