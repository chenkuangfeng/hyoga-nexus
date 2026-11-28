"""Single Native orchestrator; protocol, completion, context, hooks and tools are modules.

GA a9a36b4 loop/handler behavior and WeKnora e1f9a6166 response guards are translated
into async execution; platform code does not wrap this in a second model/tool loop.
"""
from __future__ import annotations
import asyncio
import time
from dataclasses import replace
from typing import Sequence
from nexus_core.native import HookContext, NativePolicy
from nexus_core.runtime import (
    LifecycleEvent, ModelMessage, RunContext, RunRequest, RuntimeCapabilities, RuntimeFault,
    RuntimeOutcome, RuntimeProgress, ToolDefinition,
)
from nexus_runtimes.native.context import resolve_incomplete_exchanges
from nexus_runtimes.native.context.assembler import ContextAssembler
from nexus_runtimes.native.context.working import WorkingMemory, apply_checkpoint
from nexus_runtimes.native.hooks import HookRegistry
from .completion import CompletionJudge, JudgeDecision
from .turn import TurnExecutor, TurnResponse
from .dispatcher import ToolDispatcher


def _trajectory_request_snapshot(messages: Sequence[ModelMessage],
                                 definitions: Sequence[ToolDefinition]) -> dict[str, object]:
    """Capture the vendor-neutral request view for later authorized inspection."""
    return {
        'messages': [{
            'role': message.role,
            'content': message.content,
            'tool_call_id': message.tool_call_id,
            'tool_calls': [{'id': call.id, 'name': call.name, 'arguments': call.arguments}
                           for call in message.tool_calls],
        } for message in messages],
        'tools': [{
            'name': tool.name,
            'description': tool.description,
            'parameters': tool.parameters,
            'side_effects': tool.side_effects,
            'requires_approval': tool.requires_approval,
        } for tool in definitions],
    }


def _trajectory_response_snapshot(response: TurnResponse) -> dict[str, object]:
    """Capture model text and structured calls without provider SDK objects."""
    return {
        'text': response.text,
        'finish_reason': response.finish_reason,
        'tool_calls': [{'id': call.id, 'name': call.name, 'arguments': call.arguments}
                       for call in response.calls],
    }


#: Sent on the last allowed turn, where tools are withdrawn so the model must answer (3.7).
FINAL_ANSWER_HINT = ('This is the last allowed turn and tools are disabled. '
                     'Give the final answer from the information already gathered.')


class AttemptCounter:
    """Run-scoped count of real model requests (3.15). Stored in progress.model_attempts.

    `begin_attempt` runs before each request, so a refused request is never sent. Retries count
    as separate attempts because each one is a billable provider call.
    """

    def __init__(self, progress: RuntimeProgress, store, limit: int):
        self.progress, self.store, self.limit = progress, store, limit

    async def begin_attempt(self) -> None:
        if self.progress.model_attempts >= self.limit:
            raise RuntimeFault('budget_exhausted')
        self.progress.model_attempts += 1
        await self.store.emit('model.attempt', {'attempt': self.progress.model_attempts, 'turn': self.progress.turns})


class RunOrchestrator:
    """Own one Run's lifecycle: budgets, cancellation, durable events and the turn loop (3.4).

    Model, context, completion and tool work are delegated to TurnExecutor, ContextAssembler,
    CompletionJudge and ToolDispatcher. One orchestrator serves exactly one Run; the worker builds
    a new instance per Run and never reuses it.
    

    Existing lifecycle callbacks remain supported. Typed context hooks may append context
    or done prompts, but neither hooks nor behavior settings alter registered tool grants.
    Progress state survives waiting_input resumes, including working memory and guards.
    """
    def __init__(self, model, tools, store, *, hooks=(), policy: NativePolicy | None = None,
                 transforms: HookRegistry | None = None, compaction_model_factory=None):
        self.model, self.tools, self.store = model, tools, store
        self.hooks, self.policy = list(hooks), policy or NativePolicy()
        self.transforms = transforms or HookRegistry()
        # Builds the configured compaction model per summary call (P3); None means the Run's own model.
        self.compaction_model_factory = compaction_model_factory
        self.dispatcher = ToolDispatcher(tools, parallel=self.policy.parallel_reads,
                                         repeat_warn_at=self.policy.tool_repeat_warn_at,
                                         repeat_stop_at=self.policy.tool_repeat_stop_at,
                                         failure_stop_at=self.policy.tool_failure_stop_at)
        self.turn_executor = TurnExecutor(self.model, self.store, self.policy)
        self.context = ContextAssembler(self.model, self.store, self.policy, compaction_model_factory=compaction_model_factory)

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

    def capabilities(self) -> RuntimeCapabilities:
        """The Native backend supports every optional capability in the runtime contract."""
        return RuntimeCapabilities()

    async def run(self, request: RunRequest, context: RunContext) -> RuntimeOutcome:
        """Execute until a real answer, durable wait, explicit exit or bounded failure.

        All model calls remain within Run budgets. Pending tools are resolved without replay
        after a wait/exit. Cleanup occurs even for cancellation and unexpected adapter faults.
        """
        run_id, messages, budget = request.run_id, request.messages, request.budget
        token, progress = context.token, context.progress or RuntimeProgress()
        attempt_limit = budget.max_model_attempts or budget.max_rounds * (self.policy.model_retries + 1)
        bind_attempts = getattr(self.model, 'bind_attempts', None)
        if callable(bind_attempts):
            bind_attempts(AttemptCounter(progress, self.store, attempt_limit))
        started, previous_seconds = time.monotonic(), progress.active_seconds
        state = progress.state
        history = list(messages) if state.get('pending_calls') else list(resolve_incomplete_exchanges(messages))
        if history and history[-1].role == 'user':
            state.pop('tool_guard', None)  # resumed with the user's answer: earlier repeats no longer count
        judge = CompletionJudge(self.policy, state)
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
                self.context.freeze(definitions)
                await self._hook(run_id, 'agent.before')
                await self._transform(run_id, 'agent.before', progress.turns, history, done)
                if self.policy.project_name and not state.get('project_injected'):
                    await append(ModelMessage('user', '[PROJECT MODE: ' + self.policy.project_name + ']\n' + self.policy.project_context))
                    state['project_injected'] = True
                if state.get('pending_calls'):
                    from .recovery import resume_tools
                    resumed = await resume_tools(state, self.tools, token, definitions, hook, progress.turns, append,
                                                 progress=progress, budget=budget, working=working)
                    if state.pop('checkpoint_updated', False):
                        history = apply_checkpoint(history, working.key_info)
                        working.key_info = ''
                        working.history.clear()
                        state['key_info'] = ''
                        state['history_info'] = []
                    await self.store.save_progress(progress)
                    if resumed:
                        return resumed
                while progress.turns < budget.max_rounds:
                    token.check()
                    if (budget.max_tokens > 0 and progress.tokens >= budget.max_tokens) or progress.errors >= budget.max_errors:
                        raise RuntimeFault('budget_exhausted')
                    # Steer is optional for standalone stores; production persists before returning it.
                    if hasattr(self.store, 'drain_steer'):
                        for message in await self.store.drain_steer():
                            history.append(message)
                            # New user direction clears tool-loop counts (tool-call-hardening C).
                            state.pop('tool_guard', None)
                    history, removed = await self.context.compact(history, token=token, budget=budget, progress=progress)
                    progress.turns += 1
                    turn = active_turn = progress.turns
                    await self._hook(run_id, 'turn.before', turn)
                    await self._transform(run_id, 'turn.before', turn, history, done)
                    await self.store.emit('turn.started', {'turn': turn})
                    self.context.ensure_frozen(definitions)
                    # Last allowed turn: withdraw tools and say so; any call the model still makes is refused below.
                    last_turn = progress.turns >= budget.max_rounds
                    turn_definitions = definitions
                    if last_turn:
                        turn_definitions = ()
                    view = self.context.view(history, working=working, turn=turn, definitions=turn_definitions)
                    model_history = list(view.messages)
                    if last_turn:
                        model_history.append(ModelMessage('user', FINAL_ANSWER_HINT))
                        await self.store.emit('turn.tools_disabled', {'turn': turn})
                    if budget.max_tokens > 0:
                        remaining_total = budget.max_tokens - progress.tokens
                        # For an explicitly capped Run, reserve output from its remaining allowance.
                        output_reserve = min(budget.max_output_tokens, max(256, remaining_total // 8))
                        input_allowance = remaining_total - output_reserve
                        if input_allowance <= 0:
                            raise RuntimeFault('budget_exhausted')
                        fit_failure = 'budget_exhausted'
                    else:
                        # With no cumulative cap, keep the independent model context ceiling.
                        output_reserve = budget.max_output_tokens
                        input_allowance = max(1, budget.max_context_tokens - output_reserve)
                        remaining_total = None
                        fit_failure = 'model_context_exceeded'
                    model_history, input_estimate, omitted = self.context.fit_token_budget(
                        model_history, definitions=turn_definitions, token_budget=input_allowance,
                        failure_code=fit_failure)
                    request_input_estimate = input_estimate
                    if omitted:
                        await self.store.emit('context.compacted', {'omitted_messages': omitted,
                            'strategy': 'token_budget_excerpts'})
                    remaining = remaining_total - input_estimate if remaining_total is not None else budget.max_output_tokens
                    await self.store.save_progress(progress)
                    await self._hook(run_id, 'model.before', turn)
                    trajectory_record_id = None
                    if hasattr(self.store, 'start_trajectory_record'):
                        trajectory_record_id = await self.store.start_trajectory_record(
                            turn, 1, input_estimate, _trajectory_request_snapshot(model_history, turn_definitions))
                    await self.store.emit('model.started', {'turn': turn,
                        'input_estimate_tokens': input_estimate})
                    model_hook_active = True
                    try:
                        try:
                            response = await self.turn_executor.execute(model_history, turn_definitions, remaining, token, turn, budget)
                        except Exception as exc:
                            if trajectory_record_id is not None:
                                await self.store.finish_trajectory_record(trajectory_record_id, {}, {},
                                    progress.tokens, 'failed', getattr(exc, 'code', 'model_request_failed'))
                            if not isinstance(exc, RuntimeFault) or exc.code != 'model_context_exceeded' or getattr(exc, 'output_started', False):
                                raise
                            # Provider context windows can be smaller than our configured estimate.
                            # Compact once more, aggressively trim older tool output, then retry once.
                            await self._hook(run_id, 'model.after', turn)
                            model_hook_active = False
                            old_size = sum(len(message.content) for message in model_history)
                            history, recovered = await self.context.compact(
                                history, token=token, budget=budget, progress=progress, force=True)
                            recovery_view = self.context.view(
                                history, working=working, turn=turn, definitions=turn_definitions,
                                tool_result_window_rounds=1)
                            retry_messages = list(recovery_view.messages)
                            if last_turn:
                                retry_messages.append(ModelMessage('user', FINAL_ANSWER_HINT))
                            if budget.max_tokens > 0:
                                remaining_total = budget.max_tokens - progress.tokens
                                output_reserve = min(budget.max_output_tokens, max(256, remaining_total // 8))
                                input_allowance = remaining_total - output_reserve
                                if input_allowance <= 0:
                                    raise RuntimeFault('budget_exhausted')
                                fit_failure = 'budget_exhausted'
                            else:
                                remaining_total = None
                                input_allowance = max(1, budget.max_context_tokens - budget.max_output_tokens)
                                fit_failure = 'model_context_exceeded'
                            retry_messages, retry_estimate, retry_omitted = self.context.fit_token_budget(
                                retry_messages, definitions=turn_definitions, token_budget=input_allowance,
                                failure_code=fit_failure)
                            request_input_estimate = retry_estimate
                            if not recovered and not retry_omitted and sum(len(message.content) for message in retry_messages) >= old_size:
                                await self.store.emit('context.recovery_failed', {'turn': turn, 'reason': exc.code})
                                raise exc
                            if retry_omitted:
                                await self.store.emit('context.compacted', {'omitted_messages': retry_omitted,
                                    'strategy': 'overflow_tool_trim_and_excerpts'})
                            if remaining_total is not None:
                                remaining = remaining_total - retry_estimate
                                if remaining <= 0:
                                    raise RuntimeFault('budget_exhausted')
                            else:
                                remaining = budget.max_output_tokens
                            await self.store.emit('model.recovery', {'turn': turn,
                                'reason': 'model_context_exceeded', 'action': 'compact_and_retry'})
                            await self._hook(run_id, 'model.before', turn)
                            model_hook_active = True
                            retry_record_id = None
                            if hasattr(self.store, 'start_trajectory_record'):
                                retry_record_id = await self.store.start_trajectory_record(
                                    turn, 2, retry_estimate, _trajectory_request_snapshot(retry_messages, turn_definitions))
                            await self.store.emit('model.started', {'turn': turn, 'recovery_attempt': 1,
                                'input_estimate_tokens': retry_estimate})
                            try:
                                response = await self.turn_executor.execute(
                                    retry_messages, turn_definitions, remaining, token, turn, budget)
                            except Exception as retry_error:
                                if retry_record_id is not None:
                                    await self.store.finish_trajectory_record(retry_record_id, {}, {}, progress.tokens,
                                        'failed', getattr(retry_error, 'code', 'model_request_failed'))
                                raise
                            trajectory_record_id = retry_record_id
                    finally:
                        if model_hook_active:
                            await self._hook(run_id, 'model.after', turn)
                    if response.tokens:
                        progress.tokens += response.tokens
                    else:
                        from nexus_runtimes.native.context.assembler import estimate_tokens
                        progress.tokens += request_input_estimate + estimate_tokens(response.text)
                        progress.tokens += sum(estimate_tokens(call.arguments) for call in response.calls)
                    if trajectory_record_id is not None:
                        await self.store.finish_trajectory_record(trajectory_record_id,
                            _trajectory_response_snapshot(response), response.usage, progress.tokens, 'completed')
                    completed = ('model.completed', {'turn': turn, 'tokens': progress.tokens,
                        'run_total_tokens': progress.tokens,
                        'request_input_estimate_tokens': request_input_estimate,
                        'usage': response.usage})
                    if budget.max_tokens > 0 and progress.tokens > budget.max_tokens:
                        await self.store.emit(*completed)
                        raise RuntimeFault('budget_exhausted')
                    working.record(response.text)
                    # The completion event and the assistant message are adjacent writes (P7).
                    # `message.completed` carries the turn's whole text as a stored event: streamed `message.delta`
                    # text may live only on the live event bus, and the timeline of a finished Run is rebuilt
                    # from stored events (openspec 2026-11-07-run-event-streaming).
                    group = [completed] + ([('message.completed', {'turn': turn, 'text': response.text})] if response.text else [])
                    await commit_group(events=group, message=ModelMessage('assistant', response.text, tuple(response.calls)))
                    terminal = False
                    judgement = judge.judge(response.text, response.finish_reason, response.calls)
                    if judgement.decision == JudgeDecision.INCOMPLETE_TOOL_CALL:
                        for call in response.calls:
                            await append(ModelMessage('tool', 'Not executed: model truncated tool arguments.', tool_call_id=call.id))
                        await append(ModelMessage('user', 'Tool arguments were truncated. Use smaller valid tool calls; no operation was executed.'))
                        if judgement.error_code:
                            raise RuntimeFault(judgement.error_code)
                    elif judgement.decision == JudgeDecision.RETRY_EMPTY:
                        await append(ModelMessage('user', judgement.prompt))
                        await self.store.emit('model.recovery', {'turn': turn, 'reason': 'unusable_response'})
                    elif judgement.decision in (JudgeDecision.STALLED, JudgeDecision.FAIL):
                        raise RuntimeFault(judgement.error_code)
                    elif judgement.decision == JudgeDecision.CONTINUE_TRUNCATED:
                        await append(ModelMessage('user', judgement.prompt))
                        await self.store.emit('answer.continued', {'turn': turn, 'attempt': int(state.get('continuations', 0))})
                    elif judgement.decision in (JudgeDecision.ACCEPT, JudgeDecision.ACCEPT_TRUNCATED):
                        if done:
                            await append(ModelMessage('user', done.pop(0)))
                        else:
                            outcome, terminal = RuntimeOutcome('completed'), True
                            if judgement.decision == JudgeDecision.ACCEPT_TRUNCATED:
                                await self.store.emit('answer.truncated', {'turn': turn})
                    elif last_turn:
                        # Tools are withdrawn on the final turn; a call the model still makes is refused, never run.
                        for call in response.calls:
                            await append(ModelMessage('tool', 'Not executed: tools are disabled on the final turn.', tool_call_id=call.id))
                    else:
                        dispatch = await self.dispatcher.dispatch(response.calls, definitions, token, hook, turn,
                            append=append, state=state, progress=progress, budget=budget, working=working)
                        if state.pop('checkpoint_updated', False):
                            history = apply_checkpoint(history, working.key_info)
                            working.key_info = ''
                            working.history.clear()
                            state['key_info'] = ''
                            state['history_info'] = []
                        if dispatch.terminal:
                            terminal, outcome = True, dispatch.outcome
                        elif dispatch.continuations:
                            await append(ModelMessage('user', '\n'.join(dispatch.continuations)))
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
