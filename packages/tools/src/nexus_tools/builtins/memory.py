"""Memory draft, search and consolidation entrypoints; reads use the current authorized store.

Model text never publishes memory. `propose_memory_draft` only creates a pending draft (after
screening and duplicate, tombstone and budget checks); `search_memory` returns pointers and short
snippets; `read_memory` returns the full version fenced as user data.
"""
from nexus_core.runtime import ToolDefinition, ToolResult
from nexus_tools.registry import RegisteredTool
from .services import store_of as _store


def memory_tools():
    """Expose draft creation, keyword search, full reads and a bounded index; never publish from model text."""
    async def draft(arguments, context):
        store = _store(context)
        message = await store.propose(arguments['kind'], 'session', arguments['diff'],
                                      entry_id=arguments.get('entry_id'), base_version=arguments.get('base_version'),
                                      topic=arguments.get('topic', ''), importance=arguments.get('importance'),
                                      valid_until=arguments.get('valid_until'))
        return ToolResult(message)
    async def start(arguments, context):
        store = _store(context)
        index = await store.memory_index() if hasattr(store, 'memory_index') else ''
        return ToolResult('Memory consolidation: read published entries before proposing verified changes.\n' + index,
            continuation='Only verified, reusable facts belong in memory. Merge duplicates, preserve provenance and index pointers. '
                         'Use propose_memory_draft for changes; do not publish drafts automatically. Report the original task outcome after consolidation.')
    async def read(arguments, context):
        store = _store(context)
        return ToolResult(await store.read_memory(arguments['entry_id']))
    async def search(arguments, context):
        store = _store(context)
        return ToolResult(await store.search_memory(arguments['query'], arguments.get('limit', 5)))
    draft_schema = {'type': 'object', 'properties': {
        'kind': {'enum': ['memory', 'sop', 'profile']},
        'diff': {'type': 'string', 'minLength': 1, 'maxLength': 8000},
        'entry_id': {'type': 'string', 'maxLength': 36},
        'base_version': {'type': 'integer', 'minimum': 1},
        'topic': {'type': 'string', 'maxLength': 160},
        'importance': {'type': 'integer', 'minimum': 1, 'maximum': 5},
        'valid_until': {'type': 'string', 'maxLength': 32}},
        'required': ['kind', 'diff'], 'additionalProperties': False}
    yield RegisteredTool(ToolDefinition('propose_memory_draft',
        'Propose verified memory/SOP changes for review. Pass entry_id and base_version to propose an edit of an existing entry. '
        'Give a short topic; a draft whose topic matches a published entry becomes an edit of that entry. '
        'importance is 1-5; valid_until (YYYY-MM-DD) only for time-bound notes. '
        'Use kind profile for who the user is and how they like to work (shown at the start of new conversations), '
        'memory for environment facts and conventions, sop for verified procedures.',
        draft_schema), draft, lambda r: r.data)
    yield RegisteredTool(ToolDefinition('start_long_term_update', 'Read the memory index and consolidate reusable findings.',
        {'type': 'object', 'properties': {}, 'additionalProperties': False}), start, lambda r: r.data)
    yield RegisteredTool(ToolDefinition('read_memory', 'Read a published authorized memory/SOP version.',
        {'type': 'object', 'properties': {'entry_id': {'type': 'string', 'maxLength': 36}}, 'required': ['entry_id'], 'additionalProperties': False},
        read_only=True, idempotent=True), read, lambda r: r.data)
    yield RegisteredTool(ToolDefinition('search_memory', 'Search published memory by keywords; returns ids, titles and short snippets. Use read_memory for full text.',
        {'type': 'object', 'properties': {
            'query': {'type': 'string', 'minLength': 1, 'maxLength': 200},
            'limit': {'type': 'integer', 'minimum': 1, 'maximum': 10}},
         'required': ['query'], 'additionalProperties': False},
        read_only=True, idempotent=True), search, lambda r: r.data)
