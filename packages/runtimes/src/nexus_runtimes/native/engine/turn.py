"""One bounded model response; no tool execution or persistence transaction ownership.

WeKnora think/observe guards are translated at this boundary. A capped tool request is
never executable; partial stream failures never retry here after output has been emitted.
"""
from __future__ import annotations
import asyncio
import time
from contextlib import aclosing
from dataclasses import dataclass, field
from nexus_core.runtime import ModelRequest, RuntimeFault, ToolCall

_END = object()  # sentinel: the model stream finished normally


@dataclass
class TurnResponse:
    """Accumulated public text, complete tool calls, usage and normalized terminal reason."""
    text: str = ''
    calls: list[ToolCall] = field(default_factory=list)
    finish_reason: str = ''
    tokens: int = 0
    usage: dict[str, int] = field(default_factory=dict)


class DeltaBuffer:
    """Batch streamed text into `message.delta` events (P6).

    A batch is flushed when it reaches `flush_chars`, when `flush_ms` has passed since its first
    chunk, or when the stream ends. `flush_ms == 0` keeps one event per chunk. Batching changes only
    event granularity: the concatenated text is unchanged and the final assistant message is still
    persisted whole by the caller.
    """
    def __init__(self, store, turn: int, flush_ms: int, flush_chars: int):
        self.store, self.turn = store, turn
        self.window = flush_ms / 1000
        self.limit = flush_chars
        self.parts: list[str] = []
        self.size = 0
        self.started = 0.0

    def remaining(self) -> float | None:
        """Seconds until the open batch must flush; None when nothing is buffered."""
        if not self.parts:
            return None
        return max(0.0, self.window - (time.monotonic() - self.started))

    async def add(self, text: str) -> None:
        if not self.parts:
            self.started = time.monotonic()
        self.parts.append(text)
        self.size += len(text)
        if self.window == 0 or self.size >= self.limit or time.monotonic() - self.started >= self.window:
            await self.flush()

    async def flush(self) -> None:
        if self.parts:
            text = ''.join(self.parts)
            self.parts, self.size = [], 0
            await self.store.emit('message.delta', {'text': text, 'turn': self.turn})


class _ChunkReader:
    """Read the next model chunk while flushing an open text batch on time, not only on arrival.

    The pending `anext` task survives timed wake-ups, so a flush never cancels the stream.
    Cancellation is observed at every wait, as `cancellable` does.
    """
    def __init__(self, stream, token, buffer: DeltaBuffer):
        self.stream, self.token, self.buffer = stream, token, buffer
        self.pending: asyncio.Future | None = None
        self.cancelled = asyncio.ensure_future(token.wait())

    async def _pull(self):
        try:
            return await anext(self.stream)
        except StopAsyncIteration:
            return _END

    async def next(self):
        if self.pending is None:
            self.pending = asyncio.ensure_future(self._pull())
        while True:
            done, _ = await asyncio.wait({self.pending, self.cancelled}, timeout=self.buffer.remaining(),
                                         return_when=asyncio.FIRST_COMPLETED)
            if self.cancelled in done:
                raise RuntimeFault('cancelled')
            if self.pending in done:
                task, self.pending = self.pending, None
                return task.result()
            await self.buffer.flush()  # the window expired while the model was silent

    async def close(self) -> None:
        tasks = [task for task in (self.pending, self.cancelled) if task is not None]
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def collect_response(model, request: ModelRequest, token, store, turn: int, timeout: float,
                           *, flush_ms: int = 0, flush_chars: int = 256) -> TurnResponse:
    """Validate one stream and persist deltas; invalid/prolonged streams raise stable RuntimeFault.

    Text deltas are batched by `DeltaBuffer` (P6). Defaults keep one event per chunk for callers
    that do not pass policy values.
    """
    response = TurnResponse()
    finished, output_chars = False, 0
    buffer = DeltaBuffer(store, turn, flush_ms, flush_chars)
    try:
        async with asyncio.timeout(timeout):
            async with aclosing(model.stream(request)) as stream:
                reader = _ChunkReader(stream, token, buffer)
                try:
                    while True:
                        chunk = await reader.next()
                        if chunk is _END:
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
                            await buffer.add(chunk.text)
                        elif chunk.kind == 'tool_call' and chunk.tool_call:
                            call = chunk.tool_call
                            if not call.id or len(call.id) > 255 or not call.name or len(call.name) > 64 or len(call.arguments) > 128000:
                                raise RuntimeFault('model_stream_invalid')
                            response.calls.append(call); output_chars += len(call.arguments)
                        else:
                            raise RuntimeFault('model_stream_invalid')
                        if output_chars > request.max_output_tokens * 8 or len(response.calls) > 32:
                            raise RuntimeFault('budget_exhausted')
                    await buffer.flush()
                finally:
                    await reader.close()
    except TimeoutError:
        raise RuntimeFault('model_timeout') from None
    if not finished or len({call.id for call in response.calls}) != len(response.calls):
        raise RuntimeFault('model_stream_invalid')
    if response.finish_reason in ('stop', 'tool_calls') and bool(response.calls) != (response.finish_reason == 'tool_calls'):
        raise RuntimeFault('model_stream_invalid')
    if response.finish_reason == 'content_filter':
        raise RuntimeFault('model_content_filtered')
    return response


class TurnExecutor:
    """Build one model request for a turn, stream it and return the collected response (3.5).

    The caller owns budget accounting and the model.before/after hooks, so the engine keeps the
    lifecycle order it had before this class existed.
    """

    def __init__(self, model, store, policy):
        self.model, self.store, self.policy = model, store, policy

    async def execute(self, messages, definitions, remaining: int, token, turn: int, budget):
        """Send the current context with per-request output and optional Run caps."""
        request = ModelRequest(tuple(messages), definitions, min(budget.max_output_tokens, remaining))
        return await collect_response(self.model, request, token, self.store, turn, budget.model_timeout_seconds,
                                      flush_ms=self.policy.delta_flush_ms, flush_chars=self.policy.delta_flush_chars)
