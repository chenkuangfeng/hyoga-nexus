"""Single Native orchestrator; protocol, completion, context, hooks and tools are modules.

GA a9a36b4 loop/handler behavior and WeKnora e1f9a6166 response guards are translated
into async execution; platform code does not wrap this in a second model/tool loop.
"""
from __future__ import annotations
import asyncio
import json
import time
from dataclasses import replace
from nexus_core.native import HookContext, NativePolicy
from nexus_core.runtime import (
    ExecutionBudget, LifecycleEvent, ModelMessage, ModelRequest, RuntimeFault,
    RuntimeOutcome, RuntimeProgress, ToolDisposition,
)
from nexus_runtimes.native.context import compact_history, resolve_incomplete_exchanges
from nexus_runtimes.native.context.assembly import append_context
from nexus_runtimes.native.context.working import WorkingMemory
from nexus_runtimes.native.hooks import HookRegistry
from .completion import CompletionPolicy
from .turn import collect_response
from .tools import execute_batch


def _message_bytes(messages) -> int:
    """Estimate encoded input size from content and tool-call arguments, one message at a time."""
    total = 0
    for message in messages:
        total += len(message.content.encode())
        for call in message.tool_calls:
            total += len(call.arguments.encode()) + len(call.name.encode())
    return total


class NativeEngine:
    """Compose one cancellable Run from independently tested services.

    Existing lifecycle callbacks remain supported. Typed context hooks may append context
    or done prompts, but neither hooks nor behavior settings alter registered tool grants.
    Progress state survives waiting_input resumes, including working memory and guards.
    """
    def __init__(self, model, tools, store, *, hooks=(), policy: NativePolicy | None = None,
                 transforms: HookRegistry | None = None):
        self.model, self.tools, self.store = model, tools, store
        self.hooks, self.policy = list(hooks), policy or NativePolicy()
        self.transforms = transforms or HookRegistry()

    async def _hook(self, run_id, phase, turn=0, tool_name=None):
        for hook in tuple(self.hooks):
            try:
                async with asyncio.timeout(1):
                    await hook(LifecycleEvent(run_id, phase, turn, tool_name))
            except Exception:
                await self.store.emit('hook.failed', {'phase': phase, 'turn': turn})

    async def _transform(self, run_id, phase, turn, history, done):
        result = await self.transforms.trigger(HookContext(run_id, phase, turn, tuple(history)), self.store.emit)
        for message in result.append_messages:
            history.append(message); await self.store.message(message)
        done.extend(result.done_prompts)
        if len(done) > 20:
            raise RuntimeFault('hook_done_queue_exceeded')

    async def run(self, run_id, messages, token, budget: ExecutionBudget, progress: RuntimeProgress | None = None):
        """Execute until a real answer, durable wait, explicit exit or bounded failure.

        All model calls remain within Run budgets. Pending tools are resolved without replay
        after a wait/exit. Cleanup occurs even for cancellation and unexpected adapter faults.
        """
        progress = progress or RuntimeProgress()
        started, previous_seconds = time.monotonic(), progress.active_seconds
        state = progress.state
        history = list(messages) if state.get('pending_calls') else list(resolve_incomplete_exchanges(messages))
        completion = CompletionPolicy(self.policy, state)
        working = WorkingMemory(state, self.policy)
        done = list(state.get('done_prompts', []))
        active_turn = 0
        outcome = RuntimeOutcome('failed', 'runtime_error')
        async def hook(phase, turn, name):
            await self._hook(run_id, phase, turn, name)
        async def append(message):
            identifier = await self.store.message(message)
            if identifier:
                message = replace(message, source_id=str(identifier))
            history.append(message)
        async def commit_group(events=(), message=None, progress=None):
            """Write adjacent observations in one store transaction when the store supports it (P7).

            Stores without `commit` fall back to the separate calls, so behavior is identical. Tool
            execution is never placed inside a group: its writes stay separate and short.
            """
            if hasattr(self.store, 'commit'):
                identifier = await self.store.commit(events=tuple(events), message=message, progress=progress)
            else:
                for kind, payload in events:
                    await self.store.emit(kind, payload)
                identifier = await self.store.message(message) if message is not None else None
                if progress is not None:
                    await self.store.save_progress(progress)
            if message is not None:
                history.append(replace(message, source_id=str(identifier)) if identifier else message)
            return identifier
        try:
            async with asyncio.timeout(max(0.001, budget.max_seconds - previous_seconds)):
                # Tool definitions are fixed for the Run (P4). Execution-time authorization still
                # runs per call, so a revoked tool is refused even if it is still listed here.
                definitions = await self.tools.definitions()
                definitions_chars = len(str(definitions).encode())
                await self._hook(run_id, 'agent.before')
                await self._transform(run_id, 'agent.before', progress.turns, history, done)
                if self.policy.project_name and not state.get('project_injected'):
                    await append(ModelMessage('user', '[PROJECT MODE: ' + self.policy.project_name + ']\n' + self.policy.project_context))
                    state['project_injected'] = True
                if state.get('pending_calls'):
                    from .recovery import resume_tools
                    resumed = await resume_tools(state, self.tools, token, definitions, hook, progress.turns, append,
                                                 progress=progress, budget=budget, working=working)
                    await self.store.save_progress(progress)
                    if resumed:
                        return resumed
                while progress.turns < budget.max_rounds:
                    token.check()
                    if progress.tokens >= budget.max_tokens or progress.errors >= budget.max_errors:
                        raise RuntimeFault('budget_exhausted')
                    # Steer is optional for standalone stores; production persists before returning it.
                    if hasattr(self.store, 'drain_steer'):
                        for message in await self.store.drain_steer():
                            history.append(message)
                    if self.policy.summarize_context:
                        from nexus_runtimes.native.context.compaction import compact
                        compacted, removed = await compact(self.model, tuple(history), budget.max_context_chars, token, budget, progress, self.store)
                    else:
                        compacted, removed = compact_history(tuple(history), budget.max_context_chars)
                    if removed:
                        history = list(compacted)
                        await self.store.emit('context.compacted', {'omitted_messages': removed, 'strategy': 'summary_or_archive' if self.policy.summarize_context else 'bounded_excerpts'})
                    progress.turns += 1
                    turn = active_turn = progress.turns
                    await self._hook(run_id, 'turn.before', turn)
                    await self._transform(run_id, 'turn.before', turn, history, done)
                    await self.store.emit('turn.started', {'turn': turn})
                    model_history = append_context(history, working.anchor(turn), tail=self.policy.working_memory_tail)
                    # Per-message accounting (P5): avoids repr() of the whole history on every turn.
                    input_estimate = _message_bytes(model_history) + definitions_chars
                    remaining = budget.max_tokens - progress.tokens - input_estimate
                    if remaining <= 0:
                        raise RuntimeFault('budget_exhausted')
                    await self.store.save_progress(progress)
                    await self._hook(run_id, 'model.before', turn)
                    await self.store.emit('model.started', {'turn': turn})
                    try:
                        response = await collect_response(self.model, ModelRequest(tuple(model_history), definitions,
                            min(budget.max_output_tokens, remaining)), token, self.store, turn, budget.model_timeout_seconds,
                            flush_ms=self.policy.delta_flush_ms, flush_chars=self.policy.delta_flush_chars)
                    finally:
                        await self._hook(run_id, 'model.after', turn)
                    progress.tokens += response.tokens or input_estimate + len(response.text.encode()) + sum(len(c.arguments.encode()) for c in response.calls)
                    completed = ('model.completed', {'turn': turn, 'tokens': progress.tokens, 'usage': response.usage})
                    if progress.tokens > budget.max_tokens:
                        await self.store.emit(*completed)
                        raise RuntimeFault('budget_exhausted')
                    working.record(response.text)
                    # The completion event and the assistant message are adjacent writes (P7).
                    await commit_group(events=[completed], message=ModelMessage('assistant', response.text, tuple(response.calls)))
                    terminal = False
                    if response.calls and response.finish_reason in ('length', 'max_tokens'):
                        for call in response.calls:
                            await append(ModelMessage('tool', 'Not executed: model truncated tool arguments.', tool_call_id=call.id))
                        await append(ModelMessage('user', 'Tool arguments were truncated. Use smaller valid tool calls; no operation was executed.'))
                        state['truncated_calls'] = int(state.get('truncated_calls', 0)) + 1
                        if state['truncated_calls'] >= self.policy.repeated_limit:
                            raise RuntimeFault('model_stuck')
                    elif not response.calls:
                        verdict = completion.evaluate(response.text, response.finish_reason)
                        if verdict.action == 'fail':
                            raise RuntimeFault(verdict.error_code)
                        if verdict.action == 'retry':
                            await append(ModelMessage('user', verdict.prompt))
                            await self.store.emit('model.recovery', {'turn': turn, 'reason': 'unusable_response'})
                        elif done:
                            await append(ModelMessage('user', done.pop(0)))
                        else:
                            outcome, terminal = RuntimeOutcome('completed'), True
                            if verdict.truncated:
                                await self.store.emit('answer.truncated', {'turn': turn})
                    else:
                        continuations = []
                        async for index, result in execute_batch(response.calls, definitions, self.tools, token, hook, turn, self.policy.parallel_reads):
                            call = response.calls[index]
                            if result.disposition == ToolDisposition.WAIT_APPROVAL:
                                from dataclasses import asdict
                                state['pending_calls'] = [asdict(call) for call in response.calls[index:]]
                                outcome, terminal = RuntimeOutcome('waiting_approval'), True
                                break
                            progress.errors += bool(result.error_code)
                            await append(ModelMessage('tool', result.data, tool_call_id=call.id))
                            if call.name == 'update_working_checkpoint' and not result.error_code:
                                args = json.loads(call.arguments)
                                working.key_info = str(args.get('key_info', args.get('content', '')))
                                state['key_info'] = working.key_info
                            if result.disposition != ToolDisposition.CONTINUE:
                                terminal = True
                                for deferred in response.calls[index + 1:]:
                                    await append(ModelMessage('tool', 'Not executed: previous tool ended this turn.', tool_call_id=deferred.id))
                                if result.disposition == ToolDisposition.WAIT_INPUT:
                                    outcome = RuntimeOutcome('waiting_input', question=result.data, candidates=result.candidates)
                                elif result.disposition == ToolDisposition.COMPLETE:
                                    outcome = RuntimeOutcome('failed' if result.error_code else 'completed', result.error_code)
                                elif result.exit_status in ('completed', 'failed'):
                                    outcome = RuntimeOutcome(result.exit_status, result.error_code)
                                else:
                                    raise RuntimeFault('tool_exit_invalid')
                                break
                            if result.continuation:
                                continuations.append(result.continuation)
                            if progress.errors >= budget.max_errors:
                                raise RuntimeFault('budget_exhausted')
                        if continuations and not terminal:
                            await append(ModelMessage('user', '\n'.join(continuations)))
                    await self._transform(run_id, 'turn.after', turn, history, done)
                    state['done_prompts'] = done
                    await commit_group(events=[('turn.completed', {'turn': turn})], progress=progress)
                    await self._hook(run_id, 'turn.after', turn)
                    active_turn = 0
                    # Late user corrections have priority over a natural final answer.
                    if terminal and outcome.status == 'completed' and hasattr(self.store, 'drain_steer'):
                        corrections = await self.store.drain_steer()
                        if corrections:
                            history.extend(corrections); terminal = False
                    if terminal:
                        return outcome
                raise RuntimeFault('budget_exhausted')
        except RuntimeFault as exc:
            if exc.code == 'budget_exhausted':
                await self.store.emit('budget.exhausted', {'turns': progress.turns, 'tokens': progress.tokens})
            return RuntimeOutcome('cancelled' if exc.code == 'cancelled' else 'interrupted' if exc.code == 'interrupted' else 'failed', exc.code)
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
                self.hooks.clear(); self.transforms.clear()
                try:
                    await self.model.close()
                except Exception:
                    await self.store.emit('resource.cleanup_failed', {'resource': 'model'})
