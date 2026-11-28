"""Compatible GA key_info and existing Nexus content checkpoint handler."""
from nexus_core.runtime import ToolDefinition, ToolResult
from nexus_tools.registry import RegisteredTool
from .services import store_of as _store


def checkpoint_tool():
    """Persist one session checkpoint and advance the future Run compaction boundary."""
    async def checkpoint(arguments, context):
        store = _store(context)
        if 'content' in arguments and 'key_info' in arguments and arguments['content'] != arguments['key_info']:
            return ToolResult('Conflicting checkpoint aliases', error_code='tool_arguments_invalid')
        value = arguments.get('key_info', arguments.get('content', ''))
        if not isinstance(value, str) or not value.strip():
            return ToolResult('Checkpoint summary cannot be empty', error_code='tool_arguments_invalid')
        content = value.strip()
        await store.checkpoint(content)
        return ToolResult('Working checkpoint updated; prior messages are compacted from the next model request onward.')
    schema = {'type': 'object', 'properties': {name: {'type': 'string', 'minLength': 1, 'maxLength': 8000} for name in ('key_info', 'content')},
        'anyOf': [{'required': ['key_info']}, {'required': ['content']}], 'additionalProperties': False}
    return RegisteredTool(ToolDefinition('update_working_checkpoint',
        'Save a concise session checkpoint and compact prior messages from the next model request onward.',
        schema, risk='read'), checkpoint, lambda r: r.data)
