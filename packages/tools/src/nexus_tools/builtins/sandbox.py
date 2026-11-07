"""Sandbox tools (openspec 2026-11-07-tool-expansion, section 4): files and commands in an isolated workspace.

All six live in the `sandbox` group, which is hidden unless the deployment enabled a sandbox that passed
isolation acceptance *and* the agent switched the group on. The tools never see host paths: models name
`/workspace/...` and `/outputs/...`. Reads and writes of one file are scheduled per path (`serial`), so a
read never overlaps a write of the same file while different files still run side by side.
"""
from __future__ import annotations

from nexus_core.deployment import DeploymentConfigError, section
from nexus_core.runtime import ConcurrencyHint, RuntimeFault, ToolDefinition, ToolResult
from nexus_core.sandbox import ExecResult, SandboxError
from nexus_tools.registry import RegisteredTool
from .services import sandbox_of as _session_of

_PATH = {'type': 'string', 'minLength': 1, 'maxLength': 1024,
         'description': 'Absolute virtual path under /workspace or /outputs.'}
_EXCLUSIVE = ConcurrencyHint('exclusive')


def _key(arguments: dict) -> str | None:
    """Scheduling key of a path argument: its normalized parts, or None when it cannot be normalized."""
    path = arguments.get('path')
    if not isinstance(path, str):
        return None
    parts = [part for part in path.split('/') if part not in ('', '.')]
    return None if '..' in parts else '/' + '/'.join(parts)


def _per_path(arguments: dict) -> ConcurrencyHint:
    key = _key(arguments)
    return ConcurrencyHint('serial', key) if key else _EXCLUSIVE


def sandbox_of(context):
    """The Run's sandbox session. A missing one is a refusal the model can read, not a Run-level fault: raising
    `RuntimeFault` from a side-effect tool would be reported as an interrupted (uncertain) call."""
    try:
        return _session_of(context)
    except RuntimeFault:
        raise SandboxError('sandbox_unavailable', 'the sandbox is not available for this Run') from None


def _failed(error: SandboxError) -> ToolResult:
    text = error.code + (f': {error.detail}' if error.detail else '')
    return ToolResult(text, error_code=error.code)


def _guarded(handler):
    """Turn a SandboxError into a failed ToolResult the model can act on; other errors stay errors."""
    async def run(arguments, context):
        try:
            return await handler(arguments, context)
        except SandboxError as error:
            return _failed(error)
    return run


def _exec_settings() -> tuple[float, bool]:
    """(gateway timeout for sandbox_exec, whether the sandbox network is open). An unreadable section counts as open."""
    try:
        values = section('sandbox')
    except DeploymentConfigError:
        return 135, True
    maximum = values.get('exec_timeout_max_seconds', 120)
    return (float(maximum) + 15 if isinstance(maximum, int) and not isinstance(maximum, bool) else 135,
            values.get('network', 'none') != 'none')


def _render_exec(result: ExecResult) -> str:
    head = (f'timed out after {result.duration_ms / 1000:.0f}s (killed)' if result.timed_out
            else f'exit_code: {result.exit_code}  duration: {result.duration_ms} ms')
    parts = [head]
    for label, text, cut in (('stdout', result.stdout, result.stdout_truncated), ('stderr', result.stderr, result.stderr_truncated)):
        if text:
            parts.append(f'--- {label}{" (truncated)" if cut else ""} ---\n{text}')
    return '\n'.join(parts)


def sandbox_tools():
    """The six sandbox tools. Registered under the `sandbox` group by `registration.builtins`."""
    exec_timeout, network_open = _exec_settings()

    async def list_files(arguments, context):
        entries = await sandbox_of(context).list_files(arguments.get('path', '/'), limit=arguments.get('limit', 200))
        if not entries:
            return ToolResult('(empty)')
        return ToolResult('\n'.join(f"{'dir ' if e.kind == 'dir' else 'file'} {e.size:>9}  {e.path}{'/' if e.kind == 'dir' else ''}"
                                    for e in entries))

    async def read_file(arguments, context):
        chunk = await sandbox_of(context).read_file(arguments['path'], start_line=arguments.get('start_line', 1),
                                                    max_lines=arguments.get('max_lines', 200))
        last = chunk.first_line + max(chunk.text.count('\n') + 1 if chunk.text else 0, 1) - 1
        note = (f'[lines {chunk.first_line}-{last} of {chunk.total_lines}; '
                + (f'continue with start_line={chunk.next_line}]' if chunk.next_line else 'end of file]'))
        return ToolResult(chunk.text + '\n' + note if chunk.text else note)

    async def write_file(arguments, context):
        written = await sandbox_of(context).write_file(arguments['path'], arguments['content'], append=arguments.get('append', False))
        return ToolResult(f"{'appended' if arguments.get('append') else 'wrote'} {written} bytes to {arguments['path']}")

    async def edit_file(arguments, context):
        await sandbox_of(context).edit_file(arguments['path'], arguments['old'], arguments['new'])
        return ToolResult(f"edited {arguments['path']} (1 replacement)")

    async def search_files(arguments, context):
        hits = await sandbox_of(context).search_files(arguments['query'], arguments.get('path', '/workspace'),
                                                      glob=arguments.get('glob', '*'), regex=arguments.get('regex', False),
                                                      limit=arguments.get('limit', 50))
        return ToolResult('\n'.join(f'{h.path}:{h.line}: {h.text}' for h in hits) if hits else 'no matches')

    async def execute(arguments, context):
        result = await sandbox_of(context).exec(arguments['command'], cwd=arguments.get('cwd', '/workspace'),
                                                timeout_seconds=arguments.get('timeout_seconds', 0))
        return ToolResult(_render_exec(result), error_code='sandbox_exec_timeout' if result.timed_out else None)

    def schema(properties, required=()):
        return {'type': 'object', 'properties': properties, 'required': list(required), 'additionalProperties': False}

    show = lambda r: r.data  # noqa: E731 - every sandbox result is already model-safe text without host paths
    common = dict(timeout_seconds=30)
    yield RegisteredTool(ToolDefinition('sandbox_list_files',
        'List a directory of the sandbox (use / to see the available roots).',
        schema({'path': _PATH, 'limit': {'type': 'integer', 'minimum': 1, 'maximum': 500}}),
        read_only=True, idempotent=True, concurrency=lambda a: _EXCLUSIVE, **common), _guarded(list_files), show)
    yield RegisteredTool(ToolDefinition('sandbox_read_file',
        'Read a text file of the sandbox by line range. Large files are read in pages.',
        schema({'path': _PATH, 'start_line': {'type': 'integer', 'minimum': 1},
                'max_lines': {'type': 'integer', 'minimum': 1, 'maximum': 1000}}, ['path']),
        read_only=True, idempotent=True, concurrency=_per_path, **common), _guarded(read_file), show)
    yield RegisteredTool(ToolDefinition('sandbox_search_files',
        'Search the text of files under a sandbox directory (plain text, or a regular expression with regex=true).',
        schema({'query': {'type': 'string', 'minLength': 1, 'maxLength': 500}, 'path': _PATH,
                'glob': {'type': 'string', 'maxLength': 100}, 'regex': {'type': 'boolean'},
                'limit': {'type': 'integer', 'minimum': 1, 'maximum': 100}}, ['query']),
        read_only=True, idempotent=True, concurrency=lambda a: _EXCLUSIVE, **common), _guarded(search_files), show)
    yield RegisteredTool(ToolDefinition('sandbox_write_file',
        'Create or replace a file in the sandbox (append=true adds to the end). Put deliverables under /outputs.',
        schema({'path': _PATH, 'content': {'type': 'string', 'maxLength': 2_000_000}, 'append': {'type': 'boolean'}},
               ['path', 'content']),
        side_effects=True, risk='write', concurrency=_per_path, **common), _guarded(write_file), show)
    yield RegisteredTool(ToolDefinition('sandbox_edit_file',
        'Replace one exact piece of text in a sandbox file. `old` must occur exactly once; add surrounding lines to make it unique.',
        schema({'path': _PATH, 'old': {'type': 'string', 'minLength': 1, 'maxLength': 200_000},
                'new': {'type': 'string', 'maxLength': 200_000}}, ['path', 'old', 'new']),
        side_effects=True, risk='write', concurrency=_per_path, **common), _guarded(edit_file), show)
    # Inside an isolated container without network the effect of a command stays in the workspace, so it is a
    # `write`; with the network open it can reach other systems and becomes `destructive` (every call asks).
    yield RegisteredTool(ToolDefinition('sandbox_exec',
        'Run a shell command in the sandbox (default directory /workspace). Output is limited; long output keeps its start and end.',
        schema({'command': {'type': 'string', 'minLength': 1, 'maxLength': 20000}, 'cwd': _PATH,
                'timeout_seconds': {'type': 'integer', 'minimum': 1, 'maximum': 3600}}, ['command']),
        side_effects=True, risk='destructive' if network_open else 'write', timeout_seconds=exec_timeout), _guarded(execute), show)
