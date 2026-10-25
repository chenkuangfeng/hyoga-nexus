"""Vendor-neutral budgets contracts; no SDK, database or platform imports."""
from __future__ import annotations
import math
from dataclasses import dataclass, field


@dataclass
class ExecutionBudget:
    """Positive finite execution limits, validated on construction.

    Invalid values raise ValueError; the Runtime decides how to account for each limit."""
    max_rounds: int = 12
    max_tokens: int = 16000
    max_output_tokens: int = 2048
    max_seconds: float = 120
    model_timeout_seconds: float = 60
    max_errors: int = 4
    max_context_chars: int = 100000

    def __post_init__(self) -> None:
        if any(not math.isfinite(value) or value <= 0 for value in vars(self).values()):
            raise ValueError('Execution budgets must be positive')


@dataclass
class RuntimeProgress:
    """Persistable counters and versioned-by-caller state for resume across worker leases."""
    turns: int = 0
    tokens: int = 0
    errors: int = 0
    active_seconds: float = 0
    state: dict[str, object] = field(default_factory=dict)
