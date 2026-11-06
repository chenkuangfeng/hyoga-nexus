"""Past-conversation search and paging (openspec 2026-11-06-memory-evolution stage 4, D1).

Both tools are read-only and belong to the memory group: the memory switches remove them with the other
memory tools. Results come from the caller's own other sessions in the Run's space, word for word.
"""
from nexus_core.runtime import ToolDefinition, ToolResult
from nexus_tools.registry import RegisteredTool
from .services import store_of as _store


def conversation_tools():
    """Expose `search_conversations` (snippets with session id and sequence) and `read_conversation` (a page)."""
    async def search(arguments, context):
        return ToolResult(await _store(context).search_conversations(arguments['query'], arguments.get('limit', 5)))

    async def read(arguments, context):
        return ToolResult(await _store(context).read_conversation(
            arguments['session_id'], arguments['sequence'], arguments.get('before', 5), arguments.get('after', 5)))

    yield RegisteredTool(ToolDefinition(
        'search_conversations',
        'Search earlier conversations with this user by keywords; returns session id, message sequence and a snippet. '
        'Use it for details that are not in memory, such as what was decided or said in a past session.',
        {'type': 'object', 'properties': {
            'query': {'type': 'string', 'minLength': 1, 'maxLength': 200},
            'limit': {'type': 'integer', 'minimum': 1, 'maximum': 10}},
         'required': ['query'], 'additionalProperties': False},
        read_only=True, idempotent=True), search, lambda r: r.data)
    yield RegisteredTool(ToolDefinition(
        'read_conversation',
        'Read messages around a sequence of an earlier conversation found with search_conversations.',
        {'type': 'object', 'properties': {
            'session_id': {'type': 'string', 'maxLength': 36},
            'sequence': {'type': 'integer', 'minimum': 1},
            'before': {'type': 'integer', 'minimum': 0, 'maximum': 10},
            'after': {'type': 'integer', 'minimum': 0, 'maximum': 10}},
         'required': ['session_id', 'sequence'], 'additionalProperties': False},
        read_only=True, idempotent=True), read, lambda r: r.data)
