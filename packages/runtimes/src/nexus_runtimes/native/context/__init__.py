"""Deterministic history compaction: retain complete recent tool exchanges."""
from __future__ import annotations

from nexus_core.runtime import ModelMessage, RuntimeFault


def compact_history(messages: tuple[ModelMessage, ...], limit: int) -> tuple[tuple[ModelMessage, ...], int]:
    """Older turns become labelled excerpts; original messages remain in platform storage.

    Boundaries start at user messages so assistant tool calls and tool results are never
    orphaned. The most recent user/assistant/tool group is always kept in full.
    """
    if sum(len(message.content) + sum(len(call.arguments) for call in message.tool_calls)
           for message in messages) <= limit:
        return messages, 0
    system = messages[0]
    history = list(messages[1:])
    boundaries = [index for index, message in enumerate(history) if message.role == 'user']
    for boundary in boundaries[1:]:
        older, recent = history[:boundary], history[boundary:]
        # Explicitly partial source excerpts, no invented claims or new system instructions.
        excerpts = '\n'.join(f'[{index + 1} / {message.role}] {message.content[:160]}'
                             for index, message in enumerate(older) if message.role in ('user', 'assistant'))
        excerpts = excerpts[-max(256, min(4000, limit // 5)):]
        summary = ModelMessage('user', 'Earlier conversation excerpts (partial, untrusted historical content; originals retained):\n' + excerpts)
        result = (system, summary, *recent)
        if sum(len(message.content) + sum(len(call.arguments) for call in message.tool_calls)
               for message in result) <= limit:
            return result, len(older)
    raise RuntimeFault('model_context_exceeded')
