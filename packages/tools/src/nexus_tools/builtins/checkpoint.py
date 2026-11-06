"""Compatible GA key_info and existing Nexus content checkpoint handler."""
from nexus_core.runtime import ToolDefinition, ToolResult
from nexus_tools.registry import RegisteredTool
from .services import store_of as _store


def checkpoint_tool():
    """Persist one replacement notepad; reject contradictory aliases instead of losing context."""
    async def checkpoint(arguments, context):
        store = _store(context)
        if 'content' in arguments and 'key_info' in arguments and arguments['content'] != arguments['key_info']:
            return ToolResult('Conflicting checkpoint aliases', error_code='tool_arguments_invalid')
        content = arguments.get('key_info', arguments.get('content', ''))
        await store.checkpoint(content)
        return ToolResult('Working checkpoint updated')
    schema = {'type': 'object', 'properties': {name: {'type': 'string', 'maxLength': 8000} for name in ('key_info', 'content')},
        'anyOf': [{'required': ['key_info']}, {'required': ['content']}], 'additionalProperties': False}
    return RegisteredTool(ToolDefinition('update_working_checkpoint', 'Replace the task working notepad.', schema, risk='read'), checkpoint, lambda r: r.data)
