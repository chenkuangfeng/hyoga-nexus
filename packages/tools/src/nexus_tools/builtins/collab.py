"""Collaboration tool (openspec 2026-11-07-tool-expansion, section 8.1): `delegate_task`, group `collab`.

The model hands a self-contained task to a sub-agent that works with a subset of its own tools and returns one
answer. The runner (`nexus_worker.subagent`) enforces the limits; this definition only carries the request.
"""
from __future__ import annotations

from nexus_core.runtime import RuntimeFault, ToolDefinition, ToolResult
from nexus_tools.registry import RegisteredTool
from .services import store_of

SUBAGENT_TIMEOUT_SECONDS = 300


def collab_tools():
    """The `delegate_task` tool."""
    async def delegate(arguments, context):
        runner = getattr(store_of(context), 'delegate', None)
        if runner is None:
            return ToolResult('delegate_unavailable: delegation is not available for this Run', error_code='delegate_unavailable')
        try:
            answer, error = await runner.run(arguments['task'], arguments.get('context', ''), arguments.get('tools'),
                                             arguments.get('max_rounds'))
        except RuntimeFault as fault:
            if fault.code in ('cancelled', 'interrupted'):
                raise
            return ToolResult(f'delegation failed: {fault.code}', error_code=fault.code)
        if error:
            return ToolResult(f'delegation failed: {error}' + (f'\nPartial result:\n{answer}' if answer else ''), error_code=error)
        return ToolResult(answer)

    schema = {'type': 'object', 'properties': {
        'task': {'type': 'string', 'minLength': 1, 'maxLength': 8000,
                 'description': 'A self-contained description of the work and the result you need.'},
        'context': {'type': 'string', 'maxLength': 20000, 'description': 'Facts the sub-agent needs; it cannot see this conversation.'},
        'tools': {'type': 'array', 'items': {'type': 'string', 'maxLength': 64}, 'maxItems': 40,
                  'description': 'Names of your tools to lend it; omit to lend all it may use.'},
        'max_rounds': {'type': 'integer', 'minimum': 1, 'maximum': 20}},
        'required': ['task'], 'additionalProperties': False}
    yield RegisteredTool(ToolDefinition('delegate_task',
        'Hand a self-contained task to a sub-agent and get its answer. It cannot see this conversation, ask the user, '
        'delegate again or use anything you do not have. Actions that need approval are refused inside it.',
        schema, side_effects=True, risk='write', timeout_seconds=SUBAGENT_TIMEOUT_SECONDS), delegate, lambda r: r.data)
