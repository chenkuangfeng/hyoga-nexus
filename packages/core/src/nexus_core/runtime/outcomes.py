"""Vendor-neutral outcomes contracts; no SDK, database or platform imports."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class RuntimeOutcome:
    """Final execution status and stable error classification returned to the platform."""
    status: Literal['completed', 'failed', 'cancelled', 'interrupted', 'waiting_input', 'waiting_approval']
    error_code: str | None = None
    question: str | None = None
    candidates: tuple[str, ...] = ()
