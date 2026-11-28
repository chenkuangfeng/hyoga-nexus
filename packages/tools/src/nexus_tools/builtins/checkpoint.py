"""Persist a Native working checkpoint with GenericAgent-compatible arguments."""
from nexus_core.runtime import ToolDefinition, ToolResult
from nexus_tools.registry import RegisteredTool
from .services import store_of as _store


def checkpoint_tool():
    """Persist one session checkpoint and advance the future Run compaction boundary."""
    async def checkpoint(arguments, context):
        store = _store(context)
        value = arguments.get('key_info', arguments.get('content', ''))
        if not isinstance(value, str) or not value.strip():
            return ToolResult('Checkpoint summary cannot be empty', error_code='tool_arguments_invalid')
        content = value.strip()
        await store.checkpoint(content)
        return ToolResult('Working checkpoint updated; prior messages are compacted from the next model request onward.')
    schema = {'type': 'object',
        'properties': {'key_info': {'type': 'string', 'minLength': 1, 'maxLength': 8000}},
        'required': ['key_info'], 'additionalProperties': False}
    return RegisteredTool(ToolDefinition('update_working_checkpoint',
        'Save a concise session checkpoint and compact prior messages from the next model request onward.',
        schema, risk='read'), checkpoint, lambda r: r.data)
