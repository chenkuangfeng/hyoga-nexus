"""GA ask_user semantics mapped to durable platform input, including quick-select choices."""
from nexus_core.runtime import ToolDefinition, ToolDisposition, ToolResult
from nexus_tools.registry import RegisteredTool


def ask_user_tool():
    """Return a tool whose optional candidates survive the complete wait/resume boundary."""
    async def ask(arguments, context):
        return ToolResult(arguments['question'], disposition=ToolDisposition.WAIT_INPUT,
                          candidates=tuple(arguments.get('candidates', [])))
    schema = {'type': 'object', 'properties': {'question': {'type': 'string', 'minLength': 1, 'maxLength': 4000},
        'candidates': {'type': 'array', 'maxItems': 12, 'items': {'type': 'string', 'minLength': 1, 'maxLength': 500}}},
        'required': ['question'], 'additionalProperties': False}
    return RegisteredTool(ToolDefinition('ask_user', 'Ask a question with optional quick-select choices.', schema), ask, lambda r: r.data)
