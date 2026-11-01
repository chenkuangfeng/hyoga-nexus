"""Paged reader for externalized tool output (P2).

Reads go through the Run's store, which only serves outputs of the same Run. The result is data,
not instructions, and is itself never externalized (the gateway exempts this tool name).
"""
from nexus_core.native.policy import TOOL_OUTPUT_READER
from nexus_core.runtime import ToolDefinition, ToolResult
from nexus_tools.registry import RegisteredTool
from .services import store_of as _store


def tool_output_tools():
    """Expose one read-only tool that returns the next page of a stored output by handle and offset."""
    async def read(arguments, context):
        store = _store(context)
        offset = arguments.get('offset', 0)
        page = await store.read_tool_output(arguments['handle'], offset)
        if page is None:
            return ToolResult('tool_output_not_found', error_code='tool_output_not_found')
        text, total, following = page
        note = (f'\n[本页为 {offset}-{offset + len(text)} / 共 {total} 字符；'
                + (f'继续读取请传入 offset={following}]' if following is not None else '已到末尾]'))
        return ToolResult(text + note)
    schema = {'type': 'object', 'properties': {
        'handle': {'type': 'string', 'minLength': 36, 'maxLength': 36},
        'offset': {'type': 'integer', 'minimum': 0, 'maximum': 1000000000}},
        'required': ['handle'], 'additionalProperties': False}
    yield RegisteredTool(ToolDefinition(TOOL_OUTPUT_READER,
        'Read the next page of a large tool output by its artifact handle and offset.', schema,
        read_only=True, idempotent=True), read, lambda r: r.data)
