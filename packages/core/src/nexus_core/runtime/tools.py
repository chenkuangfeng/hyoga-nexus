"""Vendor-neutral tools contracts; no SDK, database or platform imports."""
from __future__ import annotations
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal, Protocol
from .cancellation import CancellationTokenPort


@dataclass(frozen=True)
class ToolCall:
    """Original model-issued call ID, tool name and JSON argument text.

    Parsing and validation occur at invocation; retaining raw arguments permits diagnostics."""
    id: str
    name: str
    arguments: str


TOOL_RISKS = ('read', 'probe', 'write', 'destructive')
RISK_LEVELS = {'read': 'low', 'probe': 'low', 'write': 'medium', 'destructive': 'high'}


@dataclass(frozen=True)
class ToolDefinition:
    """Authorized tool schema and execution properties exposed for one model turn.

    Flags describe scheduling, side effects and approval requirements; they grant no access."""
    name: str
    description: str
    parameters: dict[str, object]
    version: str = 'v1'
    side_effects: bool = False
    timeout_seconds: float = 15
    capability: Literal["python_function", "sandbox_code"] = "python_function"
    read_only: bool = False
    idempotent: bool = False
    requires_approval: bool = False
    #: Impact class (openspec 2026-11-06-tool-call-hardening D10; WeKnora `policy.go`): `read` / `probe` change
    #: nothing outside the Run, `write` changes data, `destructive` may destroy data or run arbitrary code.
    #: Combined with the agent's access level by `nexus_tools.policy.decide`; it never widens access.
    #: Omitted means `read` for a read-only tool and `write` otherwise.
    risk: Literal['read', 'probe', 'write', 'destructive'] | None = None
    # Capabilities the executing backend must provide (for example 'sandbox'); empty means none.
    required_capabilities: tuple[str, ...] = ()

    def __post_init__(self):
        # A read-only declaration is a scheduling promise (P9): such a tool may run in parallel,
        # so it must not carry side effects or require approval.
        if self.read_only and (self.side_effects or self.requires_approval):
            raise ValueError(f'Read-only tool {self.name!r} must not declare side effects or approval')
        if self.risk is None:
            object.__setattr__(self, 'risk', 'read' if self.read_only else 'write')
        if self.risk not in TOOL_RISKS:
            raise ValueError(f'Tool {self.name!r} has unknown risk {self.risk!r}')
        if self.read_only and self.risk not in ('read', 'probe'):
            raise ValueError(f'Read-only tool {self.name!r} must be read or probe risk')

    @property
    def risk_level(self) -> str:
        """Legacy three-level label derived from `risk` (kept one release for catalog clients)."""
        return RISK_LEVELS[self.risk]


class ToolDisposition(StrEnum):
    """Control result consumed by the single Native execution loop."""
    CONTINUE = 'continue'
    COMPLETE = 'complete'
    WAIT_INPUT = 'wait_input'
    WAIT_APPROVAL = 'wait_approval'
    EXIT = 'exit'


@dataclass(frozen=True)
class ToolResult:
    """Tool observation plus continuation, suspension or termination semantics.

    candidates accompany input requests; error_code is a stable classification, not a secret."""
    data: str
    continuation: str = ''
    disposition: ToolDisposition = ToolDisposition.CONTINUE
    error_code: str | None = None
    exit_status: Literal['completed', 'failed'] | None = None
    candidates: tuple[str, ...] = ()


class ToolGatewayPort(Protocol):
    """Return currently authorized definitions and execute with cooperative cancellation.

    Implementations must recheck authority at invocation, regardless of earlier definitions."""
    async def definitions(self) -> tuple[ToolDefinition, ...]: ...
    async def execute(self, call: ToolCall, cancellation: CancellationTokenPort) -> ToolResult: ...
