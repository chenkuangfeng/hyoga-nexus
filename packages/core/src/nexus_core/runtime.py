"""Vendor- and persistence-neutral Native execution contracts."""
from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum
from typing import AsyncIterator, Literal, Protocol


class RuntimeFault(Exception):
    """Only stable codes cross execution boundaries; never retain SDK exceptions."""
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: str


@dataclass(frozen=True)
class ModelMessage:
    role: Literal['system', 'user', 'assistant', 'tool']
    content: str
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call_id: str | None = None


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    parameters: dict[str, object]
    version: str = 'v1'
    side_effects: bool = False
    timeout_seconds: float = 15
    capability: Literal["python_function", "sandbox_code"] = "python_function"


@dataclass(frozen=True)
class ModelRequest:
    messages: tuple[ModelMessage, ...]
    tools: tuple[ToolDefinition, ...]
    max_output_tokens: int


@dataclass(frozen=True)
class ModelChunk:
    kind: Literal['text', 'tool_call', 'usage', 'done']
    text: str = ''
    tool_call: ToolCall | None = None
    total_tokens: int = 0
    finish_reason: str = ''


class ChatModelPort(Protocol):
    def stream(self, request: ModelRequest) -> AsyncIterator[ModelChunk]: ...
    async def close(self) -> None: ...


class ToolDisposition(StrEnum):
    CONTINUE = 'continue'
    COMPLETE = 'complete'
    WAIT_INPUT = 'wait_input'
    EXIT = 'exit'


@dataclass(frozen=True)
class ToolResult:
    data: str
    continuation: str = ''
    disposition: ToolDisposition = ToolDisposition.CONTINUE
    error_code: str | None = None
    exit_status: Literal['completed', 'failed'] | None = None


class CancellationTokenPort(Protocol):
    async def wait(self) -> None: ...
    def check(self) -> None: ...


class ToolGatewayPort(Protocol):
    async def definitions(self) -> tuple[ToolDefinition, ...]: ...
    async def execute(self, call: ToolCall, cancellation: CancellationTokenPort) -> ToolResult: ...


@dataclass(frozen=True)
class LifecycleEvent:
    run_id: str
    phase: str
    turn: int = 0
    tool_name: str | None = None
    error_code: str | None = None


class RuntimeLifecycleHook(Protocol):
    async def __call__(self, event: LifecycleEvent) -> None: ...


@dataclass
class ExecutionBudget:
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
    turns: int = 0
    tokens: int = 0
    errors: int = 0
    active_seconds: float = 0


class RuntimeStorePort(Protocol):
    async def emit(self, kind: str, payload: dict[str, object]) -> None: ...
    async def message(self, message: ModelMessage) -> None: ...
    async def save_progress(self, progress: RuntimeProgress) -> None: ...


class MemoryDraftPort(Protocol):
    async def propose(self, kind: Literal['memory', 'sop'], scope: str, diff: str) -> str: ...


@dataclass(frozen=True)
class SandboxRequest:
    workspace_id: str
    run_id: str
    code: str
    timeout_seconds: float
    memory_mb: int
    network_allowed: bool = False


@dataclass(frozen=True)
class SandboxResult:
    output: str
    artifact_ids: tuple[str, ...] = ()


class SandboxPort(Protocol):
    """A composition root must verify isolation before exposing this capability."""
    async def execute(self, request: SandboxRequest, cancellation: CancellationTokenPort) -> SandboxResult: ...


@dataclass(frozen=True)
class RuntimeOutcome:
    status: Literal['completed', 'failed', 'cancelled', 'interrupted', 'waiting_input']
    error_code: str | None = None
    question: str | None = None
