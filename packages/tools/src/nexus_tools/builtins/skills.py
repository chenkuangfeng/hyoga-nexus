"""Skill readers: ``load_skill`` (Level 2 body) and ``read_skill_file`` (Level 3 resource).

Both are read-only. They return only skills the Run's agent version binds, and the platform store
re-checks the binding and the resource grant on every call. Skill text is task guidance; it grants no
permission, so a skill cannot make a tool available that the agent does not bind.
"""
from nexus_core.runtime import ToolDefinition, ToolResult
from nexus_tools.registry import RegisteredTool
from .services import store_of as _store

#: Skill names follow the same rule as the loader: one path segment of word characters and hyphens.
_NAME = {'type': 'string', 'minLength': 1, 'maxLength': 64, 'pattern': r'^[\w-]+$'}


def skills_tools():
    """Expose the two skill readers; both fail with the platform's generic not-found error when unbound."""
    async def load(arguments, context):
        return ToolResult(await _store(context).load_skill(arguments['name']))
    async def read_file(arguments, context):
        return ToolResult(await _store(context).read_skill_file(arguments['name'], arguments['path']))
    yield RegisteredTool(ToolDefinition('load_skill',
        'Load the full instructions of a skill bound to this agent. Use a name from the skills list.',
        {'type': 'object', 'properties': {'name': _NAME}, 'required': ['name'], 'additionalProperties': False},
        read_only=True, idempotent=True), load, lambda r: r.data)
    async def run_script(arguments, context):
        return ToolResult(await _store(context).run_skill_script(arguments['name'], arguments['script'],
                                                                arguments.get('args', {})))
    yield RegisteredTool(ToolDefinition('read_skill_file',
        'Read one resource file of a skill loaded with load_skill. The path is relative to the skill directory.',
        {'type': 'object', 'properties': {
            'name': _NAME,
            'path': {'type': 'string', 'minLength': 1, 'maxLength': 200}},
         'required': ['name', 'path'], 'additionalProperties': False},
        read_only=True, idempotent=True), read_file, lambda r: r.data)
    yield RegisteredTool(ToolDefinition('run_skill_script',
        'Run a script declared by a skill bound to this agent. Each call needs approval. Arguments are passed as JSON on stdin.',
        {'type': 'object', 'properties': {
            'name': _NAME,
            'script': {'type': 'string', 'pattern': r'^[a-z][a-z0-9_-]{0,63}$'},
            'args': {'type': 'object'}},
         'required': ['name', 'script'], 'additionalProperties': False},
        requires_approval=True, risk_level='high', side_effects=True, timeout_seconds=320), run_script, lambda r: r.data)
