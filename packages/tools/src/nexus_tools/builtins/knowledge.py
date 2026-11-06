"""Knowledge tools (openspec 2026-11-06-knowledge-base K1.8; WeKnora ``search_knowledge``, ``read_document``,
``list_documents``).

All three are read-only and search only the knowledge bases bound to the Run's agent version that the user
can read at call time (Pre-Filter in the platform store). Every passage shown to the model is numbered
``[ID:n]`` by the Run's evidence registry, kept in the Run state so numbers survive suspension; a passage
already shown is printed as a reference only (RAGFlow ``ServeText``). At the end of the Run the answer's
handles are resolved into citations.
"""
from nexus_core.runtime import ToolDefinition, ToolResult
from nexus_tools.registry import RegisteredTool
from .services import run_state_of, store_of as _store


def knowledge_tools():
    async def search(arguments, context):
        return ToolResult(await _store(context).search_knowledge(
            arguments['query'], arguments.get('kb_ids') or [], arguments.get('limit', 8), run_state_of(context),
            {'tags': arguments.get('tags') or [], 'folder': arguments.get('folder'),
             'metadata': arguments.get('metadata') or {}}))

    async def read(arguments, context):
        return ToolResult(await _store(context).read_document(
            arguments['document_id'], arguments.get('chunk', 0), arguments.get('count', 4), run_state_of(context),
            arguments.get('section')))

    async def listing(arguments, context):
        return ToolResult(await _store(context).list_documents(
            arguments.get('kb_id'), arguments.get('keyword', ''), arguments.get('offset', 0), arguments.get('limit', 30)))

    async def grep(arguments, context):
        return ToolResult(await _store(context).grep_chunks(
            arguments['pattern'], arguments.get('kb_id'), arguments.get('document_id'),
            arguments.get('ignore_case', True), arguments.get('limit', 10), run_state_of(context)))

    async def outline(arguments, context):
        return ToolResult(await _store(context).document_outline(arguments['document_id']))

    async def graph(arguments, context):
        return ToolResult(await _store(context).query_knowledge_graph(
            arguments['entities'], arguments.get('kb_id'), arguments.get('hops', 2), run_state_of(context)))

    yield RegisteredTool(ToolDefinition(
        'grep_chunks',
        'Find chunks that contain an exact piece of text (a name, number, code, clause) in the bound knowledge bases. '
        'Use it when search_knowledge is too fuzzy. Matches show a snippet around the text and are labelled [ID:n].',
        {'type': 'object', 'properties': {
            'pattern': {'type': 'string', 'minLength': 1, 'maxLength': 200},
            'kb_id': {'type': 'string', 'maxLength': 36}, 'document_id': {'type': 'string', 'maxLength': 36},
            'ignore_case': {'type': 'boolean'}, 'limit': {'type': 'integer', 'minimum': 1, 'maximum': 30}},
         'required': ['pattern'], 'additionalProperties': False},
        read_only=True, idempotent=True), grep, lambda r: r.data)
    yield RegisteredTool(ToolDefinition(
        'document_outline',
        'Show the heading structure of a knowledge document (headings or pages with their chunk numbers), so you can '
        'read one section with read_document(section=...).',
        {'type': 'object', 'properties': {'document_id': {'type': 'string', 'maxLength': 36}},
         'required': ['document_id'], 'additionalProperties': False},
        read_only=True, idempotent=True), outline, lambda r: r.data)
    yield RegisteredTool(ToolDefinition(
        'query_knowledge_graph',
        'Look up entities by exact name in the knowledge graphs of the bound knowledge bases and return them with '
        'their relations, up to `hops` steps away. Use it for questions about how things relate. Results are '
        'bounded; a note says when they were cut. Items are labelled [ID:n] for citation.',
        {'type': 'object', 'properties': {
            'entities': {'type': 'array', 'items': {'type': 'string', 'minLength': 1, 'maxLength': 120},
                         'minItems': 1, 'maxItems': 10},
            'kb_id': {'type': 'string', 'maxLength': 36},
            'hops': {'type': 'integer', 'minimum': 1, 'maximum': 3}},
         'required': ['entities'], 'additionalProperties': False},
        read_only=True, idempotent=True), graph, lambda r: r.data)
    yield RegisteredTool(ToolDefinition(
        'search_knowledge',
        'Search the knowledge bases bound to this agent (keyword and semantic search). Write `query` as focused '
        'key terms, names and synonyms, not a chat reply. Each passage is labelled [ID:n]; when the answer uses a '
        'passage, end that sentence with its [ID:n]. Never invent IDs; only cite passages returned here.',
        {'type': 'object', 'properties': {
            'query': {'type': 'string', 'minLength': 1, 'maxLength': 500},
            'kb_ids': {'type': 'array', 'items': {'type': 'string', 'maxLength': 36}, 'maxItems': 20,
                       'description': 'Optional subset of the bound knowledge base ids.'},
            'limit': {'type': 'integer', 'minimum': 1, 'maximum': 20},
            'tags': {'type': 'array', 'items': {'type': 'string', 'maxLength': 120}, 'maxItems': 10,
                     'description': 'Only documents with one of these tag names.'},
            'folder': {'type': 'string', 'maxLength': 1024, 'description': 'Only documents in this folder and below.'},
            'metadata': {'type': 'object', 'additionalProperties': {'type': 'string'}, 'maxProperties': 10,
                         'description': 'Only documents whose custom metadata has all these values.'}},
         'required': ['query'], 'additionalProperties': False},
        read_only=True, idempotent=True), search, lambda r: r.data)
    yield RegisteredTool(ToolDefinition(
        'read_document',
        'Read consecutive chunks of a knowledge document found with search_knowledge or list_documents, '
        'starting at chunk number `chunk` (0-based). Passages are labelled [ID:n] for citation.',
        {'type': 'object', 'properties': {
            'document_id': {'type': 'string', 'maxLength': 36},
            'chunk': {'type': 'integer', 'minimum': 0},
            'count': {'type': 'integer', 'minimum': 1, 'maximum': 10},
            'section': {'type': 'string', 'maxLength': 500,
                        'description': 'Read the chunks under this heading path instead (see document_outline), e.g. "第一章 > 1.1".'}},
         'required': ['document_id'], 'additionalProperties': False},
        read_only=True, idempotent=True), read, lambda r: r.data)
    yield RegisteredTool(ToolDefinition(
        'list_documents',
        'List documents of the knowledge bases bound to this agent (id, name, chunks, update time), optionally '
        'filtered by one knowledge base or a filename keyword.',
        {'type': 'object', 'properties': {
            'kb_id': {'type': 'string', 'maxLength': 36},
            'keyword': {'type': 'string', 'maxLength': 100},
            'offset': {'type': 'integer', 'minimum': 0},
            'limit': {'type': 'integer', 'minimum': 1, 'maximum': 100}},
         'additionalProperties': False},
        read_only=True, idempotent=True), listing, lambda r: r.data)
