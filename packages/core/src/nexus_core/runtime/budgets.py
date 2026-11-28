"""Vendor-neutral budgets contracts; no SDK, database or platform imports."""
from __future__ import annotations
import math
from dataclasses import dataclass, field


@dataclass
class ExecutionBudget:
    """Finite execution limits, validated on construction.

    ``max_tokens=0`` disables the optional cumulative Run token cap. Token usage is
    still recorded; per-request output, context, round, time and error limits remain.
    Invalid values raise ValueError; the Runtime decides how to account for each limit."""
    max_rounds: int = 12
    max_tokens: int = 0
    max_output_tokens: int = 2048
    max_seconds: float = 120
    model_timeout_seconds: float = 60
    max_errors: int = 4
    # Effective model input window in tokens after resolving model and agent K settings.
    max_context_tokens: int = 200000
    # Kept for older saved settings; Native execution uses max_context_tokens.
    max_context_chars: int = 100000
    # Model requests including transport retries. 0 derives max_rounds * (model_retries + 1) at run time.
    max_model_attempts: int = 0

    def __post_init__(self) -> None:
        if any(not math.isfinite(value) or value <= 0 for name, value in vars(self).items()
               if name not in ('max_model_attempts', 'max_tokens')):
            raise ValueError('Execution budgets must be positive')
        if type(self.max_tokens) is not int or self.max_tokens < 0:
            raise ValueError('max_tokens must be a non-negative integer (0 disables the cumulative cap)')
        if type(self.max_model_attempts) is not int or self.max_model_attempts < 0:
            raise ValueError('max_model_attempts must be a non-negative integer (0 derives the cap)')


@dataclass
class RuntimeProgress:
    """Persistable counters and versioned-by-caller state for resume across worker leases."""
    turns: int = 0
    tokens: int = 0
    errors: int = 0
    active_seconds: float = 0
    # Model requests actually issued, including transport retries (3.15). Older rows read as 0.
    model_attempts: int = 0
    state: dict[str, object] = field(default_factory=dict)
