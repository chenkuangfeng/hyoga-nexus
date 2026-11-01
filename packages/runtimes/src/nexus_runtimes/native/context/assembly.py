"""Model-only context assembly that never rewrites persisted source messages."""
from dataclasses import replace

from nexus_core.runtime import ModelMessage


def append_context(messages, context: str, *, tail: bool = False):
    """Insert a user-level runtime envelope without altering user text or tool exchanges.

    Working notes are not elevated into system instructions. Keeping their own envelope
    also preserves exact answered questions and continuation IDs across wait/resume.

    Default placement follows the system message, so the envelope changes on every turn and
    breaks the provider's prefix cache for all history after it. `tail=True` appends it at the
    end instead (P1): the prefix stays byte-stable across turns. Appending at the end never splits
    an assistant tool call from its results, because the envelope is placed after all of them.
    """
    result = list(messages)
    if context:
        if tail:
            result.append(ModelMessage('user', context))
        else:
            result.insert(1 if result and result[0].role == 'system' else 0, ModelMessage('user', context))
    return result


def trim_tool_results(messages, rounds: int):
    """Return a model view where tool results older than the last `rounds` model calls are one-line indexes (P2).

    Only the view changes: persisted rows and the in-memory history keep the full text. A trimmed
    result keeps its tool name and first line, so the model still knows what it did. The window
    is counted in assistant messages that issued tool calls, and it moves only when a new call is made.
    """
    rounds_at = [index for index, message in enumerate(messages) if message.role == 'assistant' and message.tool_calls]
    if len(rounds_at) <= rounds:
        return list(messages)
    cutoff = rounds_at[-rounds]
    names = {call.id: call.name for message in messages if message.role == 'assistant' for call in message.tool_calls}
    result = list(messages)
    for index in range(cutoff):
        message = messages[index]
        if message.role == 'tool':
            first = (message.content.splitlines() or [''])[0][:160]
            name = names.get(message.tool_call_id, 'unknown')
            result[index] = replace(message, content=f'[历史工具结果已省略：{name}] {first}')
    return result
