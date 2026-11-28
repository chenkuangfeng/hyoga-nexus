"""Sub-agent runs for `delegate_task` (openspec 2026-11-07-tool-expansion, section 8.1).

A delegated task runs as a nested Native Run inside the parent's tool call:

- its tools are a subset of the parent's bindings (never wider, whatever the model asks for), minus the tools
  that need a human or change the parent's own state (`ask_user`, checkpoints, memory proposals, `delegate_task`
  itself), and the `collab` group stays hidden, so a sub-agent cannot delegate again;
- it gets the parent's access level and tool-group switches; actions that would need approval are refused with
  `tool_approval_unavailable` because there is nobody to ask inside a delegated run: the parent decides;
- its rounds, tokens and time are bounded by a share of the parent's budget, and the tokens it used are charged
  to the parent;
- its messages are kept in memory, not in the parent's history; only its final answer returns, as one tool result;
  tool invocations are recorded on the parent Run (same audit trail) and two events mark start and end.
"""
from __future__ import annotations

from dataclasses import replace

from nexus_core.native import NativePolicy
from nexus_core.runtime import (ExecutionBudget, ModelMessage, RunContext, RunRequest, RuntimeFault, RuntimeProgress)
from nexus_runtimes.native.engine import RunOrchestrator
from nexus_tools.builtins.services import RunServices
from nexus_tools.gateway import AuthorizedToolGateway, OutputSpill

#: Never available to a sub-agent: they need a user, or they change what the parent run owns.
EXCLUDED_TOOLS = frozenset({'delegate_task', 'ask_user', 'update_working_checkpoint', 'propose_memory_draft',
                            'start_long_term_update'})
MAX_SUB_ROUNDS = 20
DEFAULT_SUB_ROUNDS = 8
PREAMBLE = ('You are a sub-agent working on one delegated task. Use only the tools you have, stay within the task, '
            'and finish with the result alone: a concise answer the delegating agent can use directly.')


class ChildStore:
    """In-memory `RuntimeStorePort` for the nested run. Nothing here reaches the parent's history."""

    def __init__(self):
        self.messages: list[ModelMessage] = []

    async def emit(self, kind: str, payload: dict) -> None:
        return None

    async def message(self, message: ModelMessage):
        self.messages.append(message)
        return None

    async def save_progress(self, progress) -> None:
        return None

    async def drain_steer(self) -> list:
        return []

    @property
    def answer(self) -> str:
        for message in reversed(self.messages):
            if message.role == 'assistant' and message.content.strip():
                return message.content.strip()
        return ''


class NoApprovalAccess:
    """The parent's tool access without `approval` and `grant`, so the gateway refuses what would need approval."""

    def __init__(self, access):
        for name in ('authorize', 'start', 'finish', 'denied', 'progress', 'spill', 'observe'):
            if hasattr(access, name):
                setattr(self, name, getattr(access, name))


class SubagentRunner:
    """Runs delegated tasks for one parent Run. Built by the worker per Run; stateless between tasks."""

    def __init__(self, *, build_model, registry, parent_bindings: dict[str, str], parent_policy: NativePolicy,
                 hidden_groups: frozenset[str], access, services_store, sandbox, token, parent_progress,
                 parent_budget: ExecutionBudget, emit, run_id: str, session_id: str, tenant_id: str):
        self.__dict__.update(locals())
        del self.__dict__['self']

    def tools_for(self, requested: list[str] | None) -> dict[str, str]:
        """The sub-agent's bindings: the parent's, minus the excluded tools, narrowed to `requested` when given."""
        allowed = {name: version for name, version in self.parent_bindings.items() if name not in EXCLUDED_TOOLS}
        if requested is None:
            return allowed
        return {name: allowed[name] for name in requested if name in allowed}

    def budget_for(self, max_rounds: int | None) -> ExecutionBudget:
        parent = self.parent_budget
        if parent.max_tokens > 0:
            remaining_tokens = max(parent.max_tokens - self.parent_progress.tokens, 0)
            tokens = min(remaining_tokens, max(4000, parent.max_tokens // 3))
            if tokens < 1000:
                raise RuntimeFault('budget_exhausted')
        else:
            tokens = 0
        return ExecutionBudget(max_rounds=min(max_rounds or DEFAULT_SUB_ROUNDS, MAX_SUB_ROUNDS, parent.max_rounds),
                               max_tokens=tokens, max_output_tokens=parent.max_output_tokens,
                               max_seconds=max(10, parent.max_seconds / 2), model_timeout_seconds=parent.model_timeout_seconds,
                               max_errors=parent.max_errors, max_context_tokens=parent.max_context_tokens,
                               max_context_chars=parent.max_context_chars)

    async def run(self, task: str, context: str = '', tools: list[str] | None = None,
                  max_rounds: int | None = None) -> tuple[str, str | None]:
        """Run one delegated task. Returns (answer, error_code); the code is None on success."""
        bindings = self.tools_for(tools)
        budget = self.budget_for(max_rounds)
        policy = replace(self.parent_policy, project_name='', project_context='')
        spill = OutputSpill(policy.tool_output_inline_limit, policy.tool_preview_chars, policy.tool_output_page_chars)
        gateway = AuthorizedToolGateway(
            self.registry, NoApprovalAccess(self.access), bindings, run_id=self.run_id, session_id=self.session_id,
            tenant_id=self.tenant_id, services=RunServices(self.services_store, {}, self.sandbox), spill=spill,
            turn_budget=policy.tool_turn_budget_chars, injection_scan=policy.tool_injection_scan,
            tool_access=policy.tool_access, hidden_groups=frozenset(self.hidden_groups) | {'collab'},
            defer_min_tokens=policy.tool_search_min_tokens)
        store, progress = ChildStore(), RuntimeProgress()
        text = task if not context.strip() else f'{task}\n\nContext:\n{context}'
        await self.emit('subagent.started', {'task': task[:200], 'tools': sorted(bindings), 'max_rounds': budget.max_rounds})
        model = self.build_model()
        try:
            orchestrator = RunOrchestrator(model, gateway, store, policy=policy)
            outcome = await orchestrator.run(
                RunRequest(f'{self.run_id}:sub', (ModelMessage('system', PREAMBLE), ModelMessage('user', text)), budget),
                RunContext(token=self.token, progress=progress))
            status, error = outcome.status, None if outcome.status == 'completed' else (outcome.error_code or outcome.status)
        except RuntimeFault as fault:
            if fault.code in ('cancelled', 'interrupted'):
                raise  # the parent run is being stopped; do not turn that into a tool result
            status, error = 'failed', fault.code
        except Exception:
            status, error = 'failed', 'runtime_error'
        finally:
            # The parent pays for what the sub-agent used, even when it failed.
            self.parent_progress.tokens += progress.tokens
            close = getattr(model, 'close', None)
            if close is not None:
                await close()
        await self.emit('subagent.finished', {'status': status, 'error': error, 'rounds': progress.turns, 'tokens': progress.tokens})
        answer = store.answer
        if error is None and not answer:
            error = 'subagent_empty_answer'
        return answer, error
