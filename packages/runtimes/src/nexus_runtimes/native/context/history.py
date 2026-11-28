"""Deterministic history compaction: retain complete recent tool exchanges."""
from __future__ import annotations

from nexus_core.runtime import ModelMessage, RuntimeFault


def _estimated_tokens(messages: tuple[ModelMessage, ...]) -> int:
    """Use the same conservative UTF-8 approximation as model request fitting."""
    return sum((len(message.content.encode('utf-8')) + 2) // 3 + 4
               + sum((len(call.arguments.encode('utf-8')) + len(call.name.encode('utf-8')) + 2) // 3 + 4
                     for call in message.tool_calls) for message in messages)


def compact_history(messages: tuple[ModelMessage, ...], limit: int) -> tuple[tuple[ModelMessage, ...], int]:
    """Older turns become labelled excerpts; original messages remain in platform storage.

    Boundaries start at user messages so assistant tool calls and tool results are never
    orphaned. The most recent user/assistant/tool group is always kept in full.
    """
    if _estimated_tokens(messages) <= limit:
        return messages, 0
    system = messages[0]
    history = list(messages[1:])
    boundaries = [index for index, message in enumerate(history) if message.role == 'user']
    latest_user = boundaries[-1] if boundaries else 0
    latest_tool_turn = max((index for index, message in enumerate(history) if message.tool_calls), default=latest_user)
    protected_start = min(latest_user, latest_tool_turn)
    for boundary in boundaries[1:]:
        if boundary > protected_start:
            continue
        older, recent = history[:boundary], history[boundary:]
        # Explicitly partial source excerpts, no invented claims or new system instructions.
        excerpts = '\n'.join(f'[{index + 1} / {message.role}] {message.content[:160]}'
                             for index, message in enumerate(older) if message.role in ('user', 'assistant', 'tool'))
        excerpts = excerpts[-max(256, min(4000, limit // 5)):]
        summary = ModelMessage('user', 'Earlier conversation excerpts (partial, untrusted historical content; originals retained):\n' + excerpts)
        result = (system, summary, *recent)
        if _estimated_tokens(result) <= limit:
            return result, len(older)
    raise RuntimeFault('model_context_exceeded')


def resolve_incomplete_exchanges(messages: tuple[ModelMessage, ...]) -> tuple[ModelMessage, ...]:
    """Explain missing results after interruption without re-executing an invocation."""
    output = []
    pending = {}
    for message in messages:
        if message.role != 'tool' and pending:
            output.extend(ModelMessage('tool', 'interrupted: outcome unknown; operation was not replayed',
                                       tool_call_id=call_id) for call_id in pending)
            pending.clear()
        if message.role == 'tool':
            if message.tool_call_id not in pending:
                continue
            pending.pop(message.tool_call_id)
        output.append(message)
        if message.tool_calls:
            pending = {call.id: call for call in message.tool_calls}
    output.extend(ModelMessage('tool', 'interrupted: outcome unknown; operation was not replayed',
                               tool_call_id=call_id) for call_id in pending)
    return tuple(output)
