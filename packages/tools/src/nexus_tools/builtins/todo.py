"""Run-scoped todo list (3.10). Lives in progress.state, so it is released when the Run ends."""
from nexus_core.runtime import ToolDefinition, ToolResult
from nexus_tools.registry import RegisteredTool
from .services import run_state_of

MAX_ITEMS = 50
MARKS = {'pending': '[ ]', 'in_progress': '[~]', 'done': '[x]'}


def _render(items) -> str:
    if not items:
        return 'No todos.'
    return '\n'.join(f"{MARKS[item['status']]} {item['text']}" for item in items)


def todo_tool():
    """`list` returns the current items; `set` replaces the whole list. Shape is enforced by the gateway schema."""
    async def todo(arguments, context):
        state = run_state_of(context)
        if arguments['op'] == 'list':
            return ToolResult(_render(state.get('todos', [])))
        if 'items' not in arguments:
            return ToolResult('Operation set requires items.', error_code='tool_arguments_invalid')
        items = [{'text': item['text'], 'status': item['status']} for item in arguments['items']]
        state['todos'] = items
        return ToolResult(_render(items))
    item = {'type': 'object', 'properties': {
        'text': {'type': 'string', 'minLength': 1, 'maxLength': 200},
        'status': {'type': 'string', 'enum': sorted(MARKS)}},
        'required': ['text', 'status'], 'additionalProperties': False}
    schema = {'type': 'object', 'properties': {
        'op': {'type': 'string', 'enum': ['list', 'set']},
        'items': {'type': 'array', 'maxItems': MAX_ITEMS, 'items': item}},
        'required': ['op'], 'additionalProperties': False}
    return RegisteredTool(ToolDefinition('todo', 'List or replace this Run\'s todo items. Statuses: pending, in_progress, done.',
                                          schema, risk='read'), todo, lambda r: r.data)
