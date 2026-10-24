"""Safe builtins; all calls still require an Agent binding and current authorization."""
from nexus_core.runtime import ToolDefinition, ToolDisposition, ToolResult
from nexus_tools.registry import RegisteredTool, ToolRegistry


def builtins(store):
    registry = ToolRegistry()
    async def ask(arguments, context):
        return ToolResult(str(arguments['question']), disposition=ToolDisposition.WAIT_INPUT)
    async def checkpoint(arguments, context):
        await store.checkpoint(str(arguments['content']))
        return ToolResult('Working checkpoint updated')
    async def draft(arguments, context):
        draft_id = await store.propose(str(arguments['kind']), 'session', str(arguments['diff']))
        return ToolResult('Draft pending review: ' + draft_id)
    for name, description, parameters, handler in (
        ('ask_user', 'Ask the user a question and wait durably for a response.',
         {'question': {'type': 'string', 'minLength': 1, 'maxLength': 4000}}, ask),
        ('update_working_checkpoint', 'Save a session working checkpoint.',
         {'content': {'type': 'string', 'maxLength': 8000}}, checkpoint),
        ('propose_memory_draft', 'Propose a session memory or SOP draft for later review; never publish it.',
         {'kind': {'enum': ['memory', 'sop']}, 'diff': {'type': 'string', 'minLength': 1, 'maxLength': 8000}}, draft),
    ):
        registry.register(RegisteredTool(ToolDefinition(name, description,
            {'type': 'object', 'properties': parameters, 'required': list(parameters), 'additionalProperties': False}),
            handler, lambda result: result.data))
    return registry
