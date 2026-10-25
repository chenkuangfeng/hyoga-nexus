"""Vendor-neutral sandbox contracts; no SDK, database or platform imports."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Protocol
from .cancellation import CancellationTokenPort


@dataclass(frozen=True)
class SandboxRequest:
    """Describe one isolated execution request without carrying a host process or SDK handle."""
    workspace_id: str
    run_id: str
    code: str
    timeout_seconds: float
    memory_mb: int
    network_allowed: bool = False


@dataclass(frozen=True)
class SandboxResult:
    """Capture sandbox output and artifact references without exposing backend internals."""
    output: str
    artifact_ids: tuple[str, ...] = ()


class SandboxPort(Protocol):
    """A composition root must verify isolation before exposing this capability."""
    async def execute(self, request: SandboxRequest, cancellation: CancellationTokenPort) -> SandboxResult: ...
