"""Native model/tool loop. Platform and worker do not wrap this with another loop."""
from __future__ import annotations

import asyncio
import time
from contextlib import aclosing
from typing import Awaitable, TypeVar

from nexus_core.runtime import (
    CancellationTokenPort, ChatModelPort, ExecutionBudget, LifecycleEvent, ModelMessage,
    ModelRequest, RuntimeFault, RuntimeLifecycleHook, RuntimeOutcome, RuntimeProgress,
    RuntimeStorePort, ToolDisposition, ToolGatewayPort,
)

from nexus_runtimes.native.context import compact_history

T = TypeVar('T')


class CancellationToken:
    def __init__(self):
        self._event = asyncio.Event()

    def cancel(self):
        self._event.set()

    def check(self):
        if self._event.is_set():
            raise RuntimeFault('cancelled')

    async def wait(self):
        await self._event.wait()


async def cancellable(operation: Awaitable[T], token: CancellationTokenPort) -> T:
    task = asyncio.ensure_future(operation)
    cancelled = asyncio.create_task(token.wait())
    try:
        done, _ = await asyncio.wait((task, cancelled), return_when=asyncio.FIRST_COMPLETED)
        if cancelled in done:
            raise RuntimeFault('cancelled')
        return await task
    finally:
        for pending in (task, cancelled):
            if not pending.done():
                pending.cancel()
        await asyncio.gather(task, cancelled, return_exceptions=True)


class NativeEngine:
    def __init__(self, model: ChatModelPort, tools: ToolGatewayPort, store: RuntimeStorePort,
                 *, hooks: tuple[RuntimeLifecycleHook, ...] = ()):
        self.model, self.tools, self.store = model, tools, store
        self.hooks = list(hooks)

    async def _hook(self, run_id: str, phase: str, turn: int = 0, tool_name: str | None = None):
        for hook in tuple(self.hooks):
            try:
                async with asyncio.timeout(1):
                    await hook(LifecycleEvent(run_id, phase, turn, tool_name))
            except Exception:
                await self.store.emit('hook.failed', {'phase': phase, 'turn': turn})

    async def run(self, run_id: str, messages: tuple[ModelMessage, ...], token: CancellationTokenPort,
                  budget: ExecutionBudget, progress: RuntimeProgress | None = None) -> RuntimeOutcome:
        progress = progress or RuntimeProgress()
        started = time.monotonic()
        previous_seconds = progress.active_seconds
        history = list(messages)
        outcome = RuntimeOutcome('failed', 'runtime_error')
        active_turn = 0
        try:
            async with asyncio.timeout(max(0.001, budget.max_seconds - previous_seconds)):
                await self._hook(run_id, 'agent.before')
                while progress.turns < budget.max_rounds:
                    token.check()
                    if progress.tokens >= budget.max_tokens or progress.errors >= budget.max_errors:
                        raise RuntimeFault('budget_exhausted')
                    compacted, removed = compact_history(tuple(history), budget.max_context_chars)
                    if removed:
                        history = list(compacted)
                        await self.store.emit('context.compacted', {'omitted_messages': removed, 'strategy': 'bounded_excerpts'})
                    progress.turns += 1
                    turn = progress.turns
                    active_turn = turn
                    end_turn = False
                    await self.store.save_progress(progress)
                    await self._hook(run_id, 'turn.before', turn)
                    await self.store.emit('turn.started', {'turn': turn})
                    definitions = await self.tools.definitions()
                    await self._hook(run_id, 'model.before', turn)
                    await self.store.emit('model.started', {'turn': turn})
                    text, calls, finished, usage = '', [], False, 0
                    output_chars = 0
                    # Conservative fallback budget for providers without usage reporting.
                    input_estimate = len(str(history)) + len(str(definitions))
                    request = ModelRequest(tuple(history), definitions,
                                           min(budget.max_output_tokens, budget.max_tokens - progress.tokens))
                    try:
                        async with asyncio.timeout(budget.model_timeout_seconds):
                            async with aclosing(self.model.stream(request)) as stream:
                                while True:
                                    try:
                                        chunk = await cancellable(anext(stream), token)
                                    except StopAsyncIteration:
                                        break
                                    if chunk.kind == 'text':
                                        if finished:
                                            raise RuntimeFault('model_stream_invalid')
                                        text += chunk.text
                                        output_chars += len(chunk.text)
                                        await self.store.emit('message.delta', {'text': chunk.text, 'turn': turn})
                                    elif chunk.kind == 'tool_call' and chunk.tool_call:
                                        call = chunk.tool_call
                                        if finished or not call.id or len(call.id) > 255 or not call.name or len(call.name) > 64 or len(call.arguments) > 128000:
                                            raise RuntimeFault('model_stream_invalid')
                                        calls.append(call)
                                        output_chars += len(chunk.tool_call.arguments)
                                    elif chunk.kind == 'usage':
                                        usage = max(usage, chunk.total_tokens)
                                    elif chunk.kind == 'done':
                                        if chunk.finish_reason == 'length':
                                            raise RuntimeFault('budget_exhausted')
                                        if chunk.finish_reason not in ('stop', 'tool_calls'):
                                            raise RuntimeFault('model_stream_invalid')
                                        finished = True
                                    if output_chars > budget.max_output_tokens * 8 or len(calls) > 32:
                                        raise RuntimeFault('budget_exhausted')
                    except TimeoutError:
                        raise RuntimeFault('model_timeout') from None
                    finally:
                        await self._hook(run_id, 'model.after', turn)
                    if not finished or len({c.id for c in calls}) != len(calls):
                        raise RuntimeFault('model_stream_invalid')
                    progress.tokens += max(usage, input_estimate + output_chars)
                    await self.store.save_progress(progress)
                    await self.store.emit('model.completed', {'turn': turn, 'tokens': progress.tokens})
                    if progress.tokens > budget.max_tokens:
                        raise RuntimeFault('budget_exhausted')
                    assistant = ModelMessage('assistant', text, tuple(calls))
                    await self.store.message(assistant)
                    history.append(assistant)
                    if not calls:
                        outcome = RuntimeOutcome('completed')
                        end_turn = True
                    else:
                        for index, call in enumerate(calls):
                            token.check()
                            await self._hook(run_id, 'tool.before', turn, call.name)
                            try:
                                result = await self.tools.execute(call, token)
                            finally:
                                await self._hook(run_id, 'tool.after', turn, call.name)
                            progress.errors += bool(result.error_code)
                            tool_message = ModelMessage('tool', result.data, tool_call_id=call.id)
                            history.append(tool_message)
                            await self.store.message(tool_message)
                            if result.disposition != ToolDisposition.CONTINUE:
                                end_turn = True
                                # Resolve remaining IDs without executing after a wait/exit.
                                for deferred in calls[index + 1:]:
                                    await self.store.message(ModelMessage('tool', 'Not executed: previous tool ended this turn.',
                                                                          tool_call_id=deferred.id))
                                if result.disposition == ToolDisposition.WAIT_INPUT:
                                    outcome = RuntimeOutcome('waiting_input', question=result.data)
                                elif result.disposition == ToolDisposition.COMPLETE:
                                    outcome = RuntimeOutcome('completed')
                                elif result.exit_status in ('completed', 'failed'):
                                    outcome = RuntimeOutcome(result.exit_status, result.error_code)
                                else:
                                    raise RuntimeFault('tool_exit_invalid')
                                break
                            if result.continuation:
                                instruction = ModelMessage('user', result.continuation)
                                history.append(instruction)
                                await self.store.message(instruction)
                            if progress.errors >= budget.max_errors:
                                raise RuntimeFault('budget_exhausted')
                    await self.store.emit('turn.completed', {'turn': turn})
                    await self._hook(run_id, 'turn.after', turn)
                    active_turn = 0
                    if end_turn:
                        return outcome
                raise RuntimeFault('budget_exhausted')
        except RuntimeFault as exc:
            if exc.code == 'budget_exhausted':
                await self.store.emit('budget.exhausted', {'turns': progress.turns, 'tokens': progress.tokens})
            return RuntimeOutcome('cancelled' if exc.code == 'cancelled' else
                                  'interrupted' if exc.code == 'interrupted' else 'failed', exc.code)
        except TimeoutError:
            return RuntimeOutcome('failed', 'budget_exhausted')
        finally:
            progress.active_seconds = previous_seconds + time.monotonic() - started
            try:
                if active_turn:
                    await self._hook(run_id, 'turn.after', active_turn)
                await self.store.save_progress(progress)
                await self._hook(run_id, 'agent.after', progress.turns)
            finally:
                self.hooks.clear()
                try:
                    await self.model.close()
                except Exception:
                    await self.store.emit('resource.cleanup_failed', {'resource': 'model'})
