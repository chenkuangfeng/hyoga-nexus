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


def _failure(error: Exception) -> ToolResult:
    """A refusal the model can act on: the stable code, and for a scan stop the findings that caused it.

    The platform's errors carry stable codes in their message (``skill_patch_ambiguous``); anything else is generic.
    """
    if not hasattr(error, 'code'):
        return ToolResult('tool_failed', error_code='tool_failed')
    text = str(error) or getattr(error, 'code', 'tool_failed')
    details = getattr(error, 'details', None) or {}
    findings = details.get('findings') or []
    if findings:
        text += '\nFindings: ' + '; '.join(f"{f.get('path')}:{f.get('line')} {f.get('rule')}" for f in findings[:5])
    return ToolResult(text, error_code=text.split(':', 1)[0].split('\n', 1)[0][:60])


def _lint(result: dict) -> str:
    notes = result.get('lint') or []
    return ('\nSuggestions (optional): ' + ' | '.join(notes)) if notes else ''


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

    async def manage(arguments, context):
        services = _store(context)
        action = arguments['action']
        try:
            result = await services.skill_manage(action, arguments)
        except Exception as error:
            return _failure(error)
        if action == 'view':
            return ToolResult(f"<draft name=\"{result['name']}\" path=\"{result['path']}\">\n{result['content']}\n</draft>\n"
                              f"Files: {', '.join(result['files']) or '(none)'}")
        if action == 'delete_draft':
            return ToolResult(f"Draft {result['name']} deleted.")
        return ToolResult(f"Draft {result['name']} updated. Files: {', '.join(result['files']) or '(none)'}.{_lint(result)}\n"
                          'Nothing is live until skill_save succeeds.')
    yield RegisteredTool(ToolDefinition('skill_manage',
        'Write or change a skill draft that the user can later save as one of their private skills. First action for an '
        'existing skill is `view`; every other edit needs the draft to have been viewed in this conversation. Actions: '
        'create (skill_md, optional files {path: text}), view (name, optional path), patch (name, old_string, new_string, '
        'optional path or replace_all; old_string must match exactly once), edit (name, skill_md: replace SKILL.md), '
        'write_file / remove_file (name, path; paths live under refs/, scripts/, assets/ or templates/), delete_draft (name). '
        'SKILL.md is YAML frontmatter then Markdown. Frontmatter: name (lowercase letters, digits, hyphens; it cannot '
        'change later) and description (one sentence under 160 bytes saying WHEN to use the skill; it is shown for '
        'every skill on every turn). Body: the steps, imperative and specific, under 250 lines; put long reference '
        'material in refs/ files and say when to read each. Scripts go in scripts/ and are run with exec_skill; they '
        'need a working sandbox. A skill grants no permissions: list the tools it needs in `tools:`. Do not write '
        'secrets into a skill. The draft is invisible to load_skill until saved.',
        {'type': 'object', 'properties': {
            'action': {'type': 'string', 'enum': ['create', 'view', 'patch', 'edit', 'write_file', 'remove_file', 'delete_draft']},
            'name': _NAME,
            'skill_md': {'type': 'string', 'maxLength': 64000},
            'files': {'type': 'object', 'additionalProperties': {'type': 'string', 'maxLength': 64000}, 'maxProperties': 50},
            'path': {'type': 'string', 'minLength': 1, 'maxLength': 200},
            'content': {'type': 'string', 'maxLength': 64000},
            'old_string': {'type': 'string', 'minLength': 1, 'maxLength': 64000},
            'new_string': {'type': 'string', 'maxLength': 64000},
            'replace_all': {'type': 'boolean'}},
         'required': ['action'], 'additionalProperties': False},
        side_effects=True, risk='write'), manage, lambda r: r.data)

    async def save(arguments, context):
        services = _store(context)
        try:
            result = await services.skill_save(arguments['name'])
        except Exception as error:
            return _failure(error)
        if result.get('unchanged'):
            return ToolResult(f"{result['skill']} is unchanged; no new version was made.")
        state = ('It is live now; load it with load_skill.' if result.get('build_state') == 'ready' else
                 'Its dependencies are being installed; it becomes available when that finishes.')
        return ToolResult(f"Saved {result['skill']} as version {result['version']} (scan: {result['verdict']}). {state}"
                          f"{_lint(result)}")
    yield RegisteredTool(ToolDefinition('skill_save',
        'Save a draft as the next version of the user\'s private skill. The user is asked to confirm every time. Only the '
        'user sees a private skill; earlier versions are kept and can be restored with skill_rollback. Refused when the '
        'scan finds something dangerous or when the draft\'s base changed since it was started.',
        {'type': 'object', 'properties': {'name': _NAME}, 'required': ['name'], 'additionalProperties': False},
        side_effects=True, risk='destructive', requires_approval=True), save, lambda r: r.data)

    async def rollback(arguments, context):
        services = _store(context)
        try:
            result = await services.skill_rollback(arguments['name'], arguments['version'])
        except Exception as error:
            return _failure(error)
        return ToolResult(f"{result['skill']} now uses version {result['version']}.")
    yield RegisteredTool(ToolDefinition('skill_rollback',
        'Make one of the user\'s private skills use a different saved version (older or newer). Nothing is deleted.',
        {'type': 'object', 'properties': {'name': _NAME, 'version': {'type': 'integer', 'minimum': 1}},
         'required': ['name', 'version'], 'additionalProperties': False},
        side_effects=True, risk='write'), rollback, lambda r: r.data)

    async def search(arguments, context):
        services = _store(context)
        found = await services.skill_search(arguments['query'], arguments.get('limit', 10))
        if not found:
            return ToolResult('No skill you can use matches that. Try other words, or work without a skill.')
        return ToolResult('\n'.join(f'{name} | {description}' for name, description in found)
                          + '\nLoad one with load_skill.')
    yield RegisteredTool(ToolDefinition('skill_search',
        'Search the skills you can use (bound to this agent, or the user\'s own private skills) by what they do. Use it '
        'when the skills list does not show one that fits, or says more exist. Returns names and descriptions; it does not '
        'load anything.',
        {'type': 'object', 'properties': {'query': {'type': 'string', 'minLength': 1, 'maxLength': 200},
                                          'limit': {'type': 'integer', 'minimum': 1, 'maximum': 10}},
         'required': ['query'], 'additionalProperties': False},
        read_only=True, idempotent=True), search, lambda r: r.data)
