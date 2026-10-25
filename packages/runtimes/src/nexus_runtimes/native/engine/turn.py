"""One bounded model response; no tool execution or persistence transaction ownership.

WeKnora think/observe guards are translated at this boundary. A capped tool request is
never executable; partial stream failures never retry here after output has been emitted.
"""
from __future__ import annotations
import asyncio
from contextlib import aclosing
from dataclasses import dataclass, field
from nexus_core.runtime import ModelRequest, RuntimeFault, ToolCall
from .cancellation import cancellable


@dataclass
class TurnResponse:
    """Accumulated public text, complete tool calls, usage and normalized terminal reason."""
    text: str = ''
    calls: list[ToolCall] = field(default_factory=list)
    finish_reason: str = ''
    tokens: int = 0
    usage: dict[str, int] = field(default_factory=dict)


async def collect_response(model, request: ModelRequest, token, store, turn: int, timeout: float) -> TurnResponse:
    """Validate one stream and persist deltas; invalid/prolonged streams raise stable RuntimeFault."""
    response = TurnResponse()
    finished, output_chars = False, 0
    try:
        async with asyncio.timeout(timeout):
            async with aclosing(model.stream(request)) as stream:
                while True:
                    try:
                        chunk = await cancellable(anext(stream), token)
                    except StopAsyncIteration:
                        break
                    if chunk.kind == 'usage':
                        response.tokens = max(response.tokens, chunk.total_tokens)
                        response.usage.update(chunk.usage)
                    elif chunk.kind == 'done':
                        if finished or chunk.finish_reason not in ('stop', 'tool_calls', 'length', 'max_tokens', 'content_filter'):
                            raise RuntimeFault('model_stream_invalid')
                        finished = True; response.finish_reason = chunk.finish_reason
                    elif finished:
                        raise RuntimeFault('model_stream_invalid')
                    elif chunk.kind == 'text':
                        response.text += chunk.text; output_chars += len(chunk.text)
                        await store.emit('message.delta', {'text': chunk.text, 'turn': turn})
                    elif chunk.kind == 'tool_call' and chunk.tool_call:
                        call = chunk.tool_call
                        if not call.id or len(call.id) > 255 or not call.name or len(call.name) > 64 or len(call.arguments) > 128000:
                            raise RuntimeFault('model_stream_invalid')
                        response.calls.append(call); output_chars += len(call.arguments)
                    else:
                        raise RuntimeFault('model_stream_invalid')
                    if output_chars > request.max_output_tokens * 8 or len(response.calls) > 32:
                        raise RuntimeFault('budget_exhausted')
    except TimeoutError:
        raise RuntimeFault('model_timeout') from None
    if not finished or len({call.id for call in response.calls}) != len(response.calls):
        raise RuntimeFault('model_stream_invalid')
    if response.finish_reason in ('stop', 'tool_calls') and bool(response.calls) != (response.finish_reason == 'tool_calls'):
        raise RuntimeFault('model_stream_invalid')
    if response.finish_reason == 'content_filter':
        raise RuntimeFault('model_content_filtered')
    return response
