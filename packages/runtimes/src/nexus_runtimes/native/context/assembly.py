"""Model-only context assembly that never rewrites persisted source messages."""
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
