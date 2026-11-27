"""Context assembly for one Run (OpenSpec native-engine-split, 3.6).

Two steps keep the engine's existing order: `compact` runs before the turn.before transforms (which
may append messages), and `view` builds the model input after them. Definitions are frozen at Run
start: `freeze` records a digest and `ensure_frozen` refuses to continue if the tool schema changed,
so the prefix the provider caches is stable for the whole Run.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

from nexus_core.runtime import RuntimeFault

from .assembly import append_context, trim_tool_results
from .history import compact_history


def message_bytes(messages) -> int:
    """Count encoded payload bytes from content and tool-call arguments, one message at a time."""
    total = 0
    for message in messages:
        total += len(message.content.encode())
        for call in message.tool_calls:
            total += len(call.arguments.encode()) + len(call.name.encode())
    return total


def estimate_tokens(text: str) -> int:
    """Conservatively estimate tokens from UTF-8 text without treating every byte as a token.

    Roughly one token per three UTF-8 bytes is deliberately above typical English token density while
    counting common CJK characters close to one token each. Provider usage replaces this estimate as
    soon as a response arrives.
    """
    size = len(text.encode('utf-8'))
    return (size + 2) // 3


def estimate_message_tokens(messages) -> int:
    """Estimate message payload plus per-message and per-tool-call protocol overhead."""
    total = 0
    for message in messages:
        total += estimate_tokens(message.content) + 4
        for call in message.tool_calls:
            total += estimate_tokens(call.arguments) + estimate_tokens(call.name) + 4
    return total


def _digest(definitions) -> str:
    return hashlib.sha256(str(definitions).encode()).hexdigest()


@dataclass(frozen=True)
class ModelView:
    """The messages sent this turn and the estimated token count used for the Run budget."""
    messages: list
    input_estimate: int


class ContextAssembler:
    """Owns compaction and the per-turn model view. Stateless between turns except the frozen digest."""

    def __init__(self, model, store, policy, *, compaction_model_factory=None):
        self.model, self.store, self.policy = model, store, policy
        self.compaction_model_factory = compaction_model_factory
        self._digest: str | None = None
        self._definitions_tokens = 0

    def freeze(self, definitions) -> None:
        """Record the tool schema for this Run. Call once, before the first turn."""
        self._digest = _digest(definitions)
        self._definitions_tokens = estimate_tokens(str(definitions))

    def ensure_frozen(self, definitions) -> None:
        """Fail explicitly if the tool schema differs from the one frozen at Run start."""
        if self._digest is None or _digest(definitions) != self._digest:
            raise RuntimeFault('context_prefix_changed')

    async def compact(self, history, *, token, budget, progress):
        """Bound the history to the Run's context limit. Returns (history, removed_count)."""
        from nexus_runtimes.native.context.compaction import compact, compact_within
        limit = budget.max_context_chars
        high = int(limit * self.policy.compact_high_ratio)
        low = int(limit * self.policy.compact_low_ratio)
        if self.policy.summarize_context:
            compacted, removed = await compact(self.model, tuple(history), limit, token, budget, progress, self.store,
                high=high, low=low, summary_max=self.policy.summary_max_chars,
                summarizer_factory=self.compaction_model_factory)
        else:
            compacted, removed = compact_within(tuple(history), high, low, limit)
        if removed:
            history = list(compacted)
            await self.store.emit('context.compacted', {'omitted_messages': removed,
                'strategy': 'summary_or_archive' if self.policy.summarize_context else 'bounded_excerpts'})
        return history, removed

    def view(self, history, *, working, turn: int, definitions=None) -> ModelView:
        """Build this turn's model view after turn.before transforms have run.

        Pass the actual turn definitions when tools are withdrawn so the estimate matches the request.
        """
        messages = append_context(trim_tool_results(history, self.policy.tool_result_window_rounds),
                                  working.anchor(turn), tail=self.policy.working_memory_tail)
        definition_tokens = self._definitions_tokens if definitions is None else estimate_tokens(str(definitions))
        return ModelView(messages, estimate_message_tokens(messages) + definition_tokens)

    def fit_token_budget(self, messages, *, definitions, token_budget: int) -> tuple[list, int, int]:
        """Compact this model view to fit the current input allowance without changing stored history.

        Run-level character compaction may not trigger when cumulative token usage is nearly exhausted.
        This deterministic pass keeps the system message and newest complete user/tool exchange intact;
        older turns become labelled excerpts. It returns fitted messages, estimated input tokens and the
        number of omitted source messages.
        """
        definition_tokens = estimate_tokens(str(definitions))
        candidate = list(messages)
        removed = 0
        while True:
            estimate = estimate_message_tokens(candidate) + definition_tokens
            if estimate <= token_budget:
                return candidate, estimate, removed
            framing = 4 * len(candidate) + 4 * sum(len(message.tool_calls) for message in candidate)
            payload_tokens = token_budget - definition_tokens - framing
            if payload_tokens <= 0:
                raise RuntimeFault('budget_exhausted')
            try:
                compacted, omitted = compact_history(tuple(candidate), payload_tokens * 3)
            except RuntimeFault:
                raise RuntimeFault('budget_exhausted') from None
            if not omitted or len(compacted) >= len(candidate):
                raise RuntimeFault('budget_exhausted')
            candidate = list(compacted)
            removed += omitted
