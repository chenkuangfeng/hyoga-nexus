"""Vendor-neutral models contracts; no SDK, database or platform imports."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import AsyncIterator, Literal, Protocol
from .tools import ToolCall, ToolDefinition


@dataclass(frozen=True)
class ModelMessage:
    """One stable history entry; tool results refer to the originating tool_call_id.

    source_id identifies persisted provenance; vendor-private replay state stays in adapters."""
    role: Literal['system', 'user', 'assistant', 'tool']
    content: str
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call_id: str | None = None
    source_id: str | None = None


@dataclass(frozen=True)
class ModelRequest:
    """Immutable sending view and authorized tool definitions for one model attempt.

    max_output_tokens bounds this attempt; conversation ownership remains with the caller."""
    messages: tuple[ModelMessage, ...]
    tools: tuple[ToolDefinition, ...]
    max_output_tokens: int


@dataclass(frozen=True)
class ModelChunk:
    """One normalized stream item; kind selects text, tool_call, usage or done fields.

    A done item describes protocol completion, not the final Run status."""
    kind: Literal['text', 'tool_call', 'usage', 'done']
    text: str = ''
    tool_call: ToolCall | None = None
    total_tokens: int = 0
    finish_reason: str = ''
    usage: dict[str, int] = field(default_factory=dict)


class ChatModelPort(Protocol):
    """Stream normalized items and release active provider resources on close.

    Implementations translate provider errors into RuntimeFault and preserve cancellation."""
    def stream(self, request: ModelRequest) -> AsyncIterator[ModelChunk]: ...
    async def close(self) -> None: ...
