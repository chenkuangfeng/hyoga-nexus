"""Runtime port: the contract every Agent execution backend implements (OpenSpec native-engine-split, 3.3).

The contract is vendor-neutral. Native and future external backends share these types; vendor SDK
types never appear here. Platform code depends on this module, not on a concrete engine.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .budgets import ExecutionBudget, RuntimeProgress
from .cancellation import CancellationTokenPort
from .models import ModelMessage
from .outcomes import RuntimeOutcome


@dataclass(frozen=True)
class RuntimeCapabilities:
    """Features a backend supports. The platform checks these before binding an Agent to a backend.

    A backend that reports a capability as False must reject requests that need it explicitly,
    never silently degrade (for example, a backend without `tools` must not expose tool definitions).
    """
    streaming: bool = True
    tools: bool = True
    waiting_input: bool = True
    cancellation: bool = True
    resume: bool = True


@dataclass(frozen=True)
class RunRequest:
    """Input for one Run: the string Run identifier and the messages already projected for this Run.

    `budget` bounds rounds, tokens, seconds and errors. Budgets are validated on construction.
    """
    run_id: str
    messages: tuple[ModelMessage, ...]
    budget: ExecutionBudget


@dataclass
class RunContext:
    """Per-Run handles that are not part of the request: cooperative cancellation and durable progress.

    `progress` is None for a fresh Run and carries state across waiting_input or approval resumes.
    """
    token: CancellationTokenPort
    progress: RuntimeProgress | None = None


class AgentRuntime(Protocol):
    """Execution backend. `run` returns exactly one terminal outcome for the Run."""

    def capabilities(self) -> RuntimeCapabilities: ...

    async def run(self, request: RunRequest, context: RunContext) -> RuntimeOutcome:
        """Execute until a terminal outcome. Must not raise for model or tool failures; report them as outcomes."""
        ...
