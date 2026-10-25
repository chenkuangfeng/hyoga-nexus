"""Model-only context assembly that never rewrites persisted source messages."""
from nexus_core.runtime import ModelMessage


def append_context(messages, context: str):
    """Insert a user-level runtime envelope without altering user text or tool exchanges.

    Working notes are not elevated into system instructions. Keeping their own envelope
    also preserves exact answered questions and continuation IDs across wait/resume.
    """
    result = list(messages)
    if context:
        result.insert(1 if result and result[0].role == 'system' else 0, ModelMessage('user', context))
    return result
