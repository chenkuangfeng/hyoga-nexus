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
    """(gateway timeout for sandbox_exec, whether any isolating sandbox profile opens the network).

    The tool definitions are shared by the whole process while an agent picks its own profile, so the answer has to
    hold for every profile: the risk is `destructive` as soon as one docker or bwrap profile has a network, and the
    timeout covers the largest `exec_timeout_max_seconds`. A `local` profile is development-only and is not counted
    as opening the network. Both the profile layout and the older flat keys are read; an unreadable section counts as
    open, which is the cautious answer.
    """
    try:
        values = section('sandbox')
    except DeploymentConfigError:
        return 135, True

    def number(table, key, default):
        value = table.get(key, default)
        return value if isinstance(value, int) and not isinstance(value, bool) else default

    profiles = values.get('profiles')
    if isinstance(profiles, dict) and profiles:
        tables = [table for table in profiles.values() if isinstance(table, dict)]
        maximum = max([number(table, 'exec_timeout_max_seconds', 120) for table in tables] or [120])
        open_network = any(table.get('type') != 'local' and table.get('network', 'none') != 'none' for table in tables)
        return float(maximum) + 15, open_network
    return float(number(values, 'exec_timeout_max_seconds', 120)) + 15, values.get('network', 'none') != 'none'


def skill_exec_settings() -> tuple[float, bool]:
    """(gateway timeout for exec_skill, whether any isolating profile opens the network).

    The gateway timeout covers the largest `skill_timeout_max_seconds` of any profile; the network answer is the one
    `sandbox_exec` uses, so the two tools carry the same risk.
    """
    _, network_open = _exec_settings()
    try:
        values = section('sandbox')
    except DeploymentConfigError:
        return 620, network_open
    tables = [t for t in (values.get('profiles') or {}).values() if isinstance(t, dict)] if isinstance(values.get('profiles'), dict) else [values]
    maxima = [t.get('skill_timeout_max_seconds', 600) for t in tables]
    maximum = max([m for m in maxima if isinstance(m, int) and not isinstance(m, bool)] or [600])
    return float(maximum) + 20, network_open


def render_exec(result: ExecResult) -> str:
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
                                                timeout_seconds=arguments.get('timeout_seconds', 0),
                                                stdin=arguments.get('stdin'))
        return ToolResult(render_exec(result), error_code='sandbox_exec_timeout' if result.timed_out else None)

    async def exec_async(arguments, context):
        job_id = await sandbox_of(context).exec_async(arguments['command'], cwd=arguments.get('cwd', '/workspace'),
                                                       timeout_seconds=arguments.get('timeout_seconds', 0))
        return ToolResult(f'started background command {job_id}. Use sandbox_job_wait to read its output.')

    def render_job(status):
        head = {'running': f'{status.job_id}: running for {status.elapsed_seconds:.0f}s',
                'finished': f'{status.job_id}: finished with exit_code {status.exit_code}',
                'cancelled': f'{status.job_id}: cancelled'}[status.state]
        body = f"\n--- output{' (last part)' if status.output_truncated else ''} ---\n{status.output}" if status.output else ''
        return head + body

    async def job_wait(arguments, context):
        status = await sandbox_of(context).job_status(arguments['job_id'], wait_seconds=arguments.get('wait_seconds', 20),
                                                       tail_chars=arguments.get('tail_chars', 4000))
        return ToolResult(render_job(status))

    async def job_cancel(arguments, context):
        return ToolResult(render_job(await sandbox_of(context).job_cancel(arguments['job_id'])))

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
        'Run a shell command in the sandbox (default directory /workspace). Output is limited; long output keeps its start and end. '
        '`stdin` is optional text for the command\'s standard input (up to 65536 bytes, kept exactly).',
        schema({'command': {'type': 'string', 'minLength': 1, 'maxLength': 20000}, 'cwd': _PATH,
                'stdin': {'type': 'string', 'maxLength': 65536},
                'timeout_seconds': {'type': 'integer', 'minimum': 1, 'maximum': 3600}}, ['command']),
        side_effects=True, risk='destructive' if network_open else 'write', timeout_seconds=exec_timeout), _guarded(execute), show)
    yield RegisteredTool(ToolDefinition('sandbox_exec_async',
        'Start a long-running shell command in the background (under /workspace) and return a job id at once. '
        'Read progress and output with sandbox_job_wait; stop it with sandbox_job_cancel. At most four run at a time.',
        schema({'command': {'type': 'string', 'minLength': 1, 'maxLength': 20000}, 'cwd': _PATH,
                'timeout_seconds': {'type': 'integer', 'minimum': 1, 'maximum': 3600}}, ['command']),
        side_effects=True, risk='destructive' if network_open else 'write', timeout_seconds=60), _guarded(exec_async), show)
    yield RegisteredTool(ToolDefinition('sandbox_job_wait',
        'Wait up to wait_seconds (default 20, at most 60) for a background command to finish, then return its state and the end of its output.',
        schema({'job_id': {'type': 'string', 'minLength': 2, 'maxLength': 16}, 'wait_seconds': {'type': 'integer', 'minimum': 0, 'maximum': 60},
                'tail_chars': {'type': 'integer', 'minimum': 200, 'maximum': 20000}}, ['job_id']),
        read_only=True, idempotent=True, concurrency=lambda a: _EXCLUSIVE, timeout_seconds=90), _guarded(job_wait), show)
    yield RegisteredTool(ToolDefinition('sandbox_job_cancel', 'Kill a background command and everything it started.',
        schema({'job_id': {'type': 'string', 'minLength': 2, 'maxLength': 16}}, ['job_id']),
        side_effects=True, risk='write', timeout_seconds=30), _guarded(job_cancel), show)
