"""Memory draft and GA consolidation entrypoint; reads use the current authorized store."""
from nexus_core.runtime import ToolDefinition, ToolResult
from nexus_tools.registry import RegisteredTool
from .services import store_of as _store


def memory_tools():
    """Expose explicit draft creation and a full available-memory index, never publish from model text."""
    async def draft(arguments, context):
        store = _store(context)
        identifier = await store.propose(arguments['kind'], 'session', arguments['diff'])
        return ToolResult('Draft pending review: ' + identifier)
    async def start(arguments, context):
        store = _store(context)
        index = await store.memory_index() if hasattr(store, 'memory_index') else ''
        return ToolResult('Memory consolidation: read published entries before proposing verified changes.\n' + index,
            continuation='Only verified, reusable facts belong in memory. Merge duplicates, preserve provenance and index pointers. '
                         'Use propose_memory_draft for changes; do not publish drafts automatically. Report the original task outcome after consolidation.')
    async def read(arguments, context):
        store = _store(context)
        return ToolResult(await store.read_memory(arguments['entry_id']))
    schema = {'type': 'object', 'properties': {'kind': {'enum': ['memory', 'sop']},
        'diff': {'type': 'string', 'minLength': 1, 'maxLength': 8000}}, 'required': ['kind', 'diff'], 'additionalProperties': False}
    yield RegisteredTool(ToolDefinition('propose_memory_draft', 'Propose verified memory/SOP changes for review.', schema), draft, lambda r: r.data)
    yield RegisteredTool(ToolDefinition('start_long_term_update', 'Read the memory index and consolidate reusable findings.',
        {'type': 'object', 'properties': {}, 'additionalProperties': False}), start, lambda r: r.data)
    yield RegisteredTool(ToolDefinition('read_memory', 'Read a published authorized memory/SOP version.',
        {'type': 'object', 'properties': {'entry_id': {'type': 'string', 'maxLength': 36}}, 'required': ['entry_id'], 'additionalProperties': False},
        read_only=True, idempotent=True), read, lambda r: r.data)
