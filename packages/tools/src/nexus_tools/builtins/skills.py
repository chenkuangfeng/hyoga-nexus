"""Skill readers: ``load_skill`` (Level 2 body) and ``read_skill_file`` (Level 3 resource).

Both are read-only. They return only skills the Run's agent version binds, and the platform store
re-checks the binding and the resource grant on every call. Skill text is task guidance; it grants no
permission, so a skill cannot make a tool available that the agent does not bind.
"""
from nexus_core.runtime import ToolDefinition, ToolResult
from nexus_core.sandbox import SandboxError
from nexus_tools.registry import RegisteredTool
from .sandbox import render_exec, skill_exec_settings
from .services import sandbox_of, store_of as _store

#: Skill names follow the same rule as the loader: one path segment of word characters and hyphens.
_NAME = {'type': 'string', 'minLength': 1, 'maxLength': 64, 'pattern': r'^[\w-]+$'}


def skills_tools():
    """Expose the two skill readers; both fail with the platform's generic not-found error when unbound."""
    async def load(arguments, context):
        services = _store(context)
        return ToolResult(await services.load_skill(arguments['name'], getattr(services, 'sandbox', None)))
    async def read_file(arguments, context):
        services = _store(context)
        return ToolResult(await services.read_skill_file(arguments['name'], arguments['path'],
                                                          getattr(services, 'sandbox', None)))
    yield RegisteredTool(ToolDefinition('load_skill',
        'Load the full instructions of a skill bound to this agent. Use a name from the skills list.',
        {'type': 'object', 'properties': {'name': _NAME}, 'required': ['name'], 'additionalProperties': False},
        read_only=True, idempotent=True), load, lambda r: r.data)
    async def exec_skill(arguments, context):
        services = _store(context)
        try:
            run = await services.exec_skill(arguments['name'], arguments['script'], arguments.get('args'),
                                            arguments.get('stdin'), arguments.get('timeout_seconds', 0),
                                            sandbox_of(context))
        except SandboxError as error:
            code = error.code + (f': {error.detail}' if error.detail else '')
            return ToolResult(code, error_code=error.code)
        if run.refused:
            note = (' The skill\'s dependencies are not installed for this sandbox profile; an administrator must rebuild them.'
                    if run.refused == 'skill_env_missing' else '')
            return ToolResult(f'Script not run: {run.refused}.{note}' if note else f'Script not run: {run.refused}',
                              error_code=run.refused)
        text = render_exec(run.result)
        if run.hint:
            text += f'\nHint: {run.hint}'
        return ToolResult(f'{run.skill} v{run.version} {run.script}\n{text}',
                          error_code='sandbox_exec_timeout' if run.result.timed_out else None)
    yield RegisteredTool(ToolDefinition('read_skill_file',
        'Read one resource file of a skill loaded with load_skill. The path is relative to the skill directory.',
        {'type': 'object', 'properties': {
            'name': _NAME,
            'path': {'type': 'string', 'minLength': 1, 'maxLength': 200}},
         'required': ['name', 'path'], 'additionalProperties': False},
        read_only=True, idempotent=True), read_file, lambda r: r.data)
    exec_timeout, network_open = skill_exec_settings()
    yield RegisteredTool(ToolDefinition('exec_skill',
        'Run one script that ships with a skill bound to this agent, in the sandbox. `script` is a path inside the skill '
        '(for example scripts/extract.py). `args` is a list of arguments, passed as they are and not interpreted by a shell; '
        '`stdin` is optional text for the script\'s standard input. The script finds its own directory in $NEXUS_SKILL_DIR '
        'and writes deliverables to $NEXUS_SKILL_OUTPUT_DIR. Steps share data through files in /workspace. For pipes or '
        'several commands in one call, use sandbox_exec instead.',
        {'type': 'object', 'properties': {
            'name': _NAME,
            'script': {'type': 'string', 'minLength': 1, 'maxLength': 200},
            'args': {'type': 'array', 'items': {'type': 'string', 'maxLength': 2000}, 'maxItems': 50},
            'stdin': {'type': 'string', 'maxLength': 65536},
            'timeout_seconds': {'type': 'integer', 'minimum': 1, 'maximum': 3600}},
         'required': ['name', 'script'], 'additionalProperties': False},
        side_effects=True, risk='destructive' if network_open else 'write', timeout_seconds=exec_timeout),
        exec_skill, lambda r: r.data)
