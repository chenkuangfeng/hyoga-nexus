"""E2B-compatible gateway adapters for templates with an operator-mounted shared workspace."""
from __future__ import annotations

import asyncio
import secrets
import shlex
import time
from pathlib import Path

from e2b import AsyncSandbox, CommandExitException

from nexus_core.sandbox import ExecResult, SandboxError
from .remote_runner import Execution
from .settings import SandboxSettings


async def execute_provider(request: Execution, settings: SandboxSettings, config: dict) -> ExecResult:
    """Create an isolated VM, verify the session volume, execute and destroy it.

    Templates must provide /nexus as the shared workspace and permit root setup. Commands run
    as the unprivileged user after virtual roots and read-only skill mounts have been prepared.
    """
    template = config.get('template')
    token_file = config.get('api_key_file')
    domain = config.get('domain')
    if (not isinstance(template, str) or not template or not isinstance(token_file, str)
            or not Path(token_file).is_absolute() or not isinstance(domain, str)
            or not domain or any(char not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-' for char in domain)):
        raise SandboxError('sandbox_provider_configuration_invalid')
    if settings.paused or not settings.enabled or request.limits != {
        'cpus': settings.cpus, 'memory_mb': settings.memory_mb, 'pids': settings.pids,
    } or request.timeout_seconds > max(settings.exec_timeout_max_seconds, settings.skill_timeout_max_seconds):
        raise SandboxError('sandbox_remote_policy_mismatch')
    key = Path(token_file).read_text().strip()
    if not key or len(key) > 1024:
        raise SandboxError('sandbox_provider_configuration_invalid')
    base = settings.root / request.tenant_id / request.session_id
    base.mkdir(parents=True, exist_ok=True)
    challenge = '.gateway-' + secrets.token_hex(16)
    marker = secrets.token_hex(32)
    (base / challenge).write_text(marker)
    sandbox = None
    started = time.monotonic()
    try:
        sandbox = await AsyncSandbox.create(
            template=template, api_key=key, domain=domain, secure=True,
            allow_internet_access=False, timeout=int(request.timeout_seconds) + 120,
            metadata={'nexus_request': request.id},
        )
        remote = f'/nexus/{request.tenant_id}/{request.session_id}'
        observed = await sandbox.files.read(f'{remote}/{challenge}', user='root')
        if observed != marker:
            raise SandboxError('sandbox_shared_workspace_unavailable')
        # Only an operator-controlled template may provide the volume and mount permissions.
        setup = (
            f'mkdir -p {shlex.quote(remote)}/workspace {shlex.quote(remote)}/outputs {shlex.quote(remote)}/skills /workspace /outputs /skills; '
            f'mount --bind {shlex.quote(remote)}/workspace /workspace && '
            f'mount --bind {shlex.quote(remote)}/outputs /outputs && '
            f'mount --bind {shlex.quote(remote)}/skills /skills && mount -o remount,bind,ro /skills && '
            'mount -t tmpfs -o size=4096,mode=000 tmpfs /nexus'
        )
        await sandbox.commands.run(setup, user='root', timeout=20)
        stdin_path = f'/tmp/nexus-stdin-{request.id}'
        await sandbox.files.write(stdin_path, request.stdin or '', user='user')
        command = f'/bin/sh -c {shlex.quote(request.command)} < {shlex.quote(stdin_path)}'
        timed_out = False
        try:
            result = await sandbox.commands.run(command, cwd=request.cwd, envs=request.env,
                                                user='user', timeout=request.timeout_seconds)
        except CommandExitException as error:
            result = error
        except TimeoutError:
            timed_out = True
            return ExecResult(None, True, '', '', False, False, int((time.monotonic() - started) * 1000))
        limit = request.output_limit
        return ExecResult(result.exit_code, timed_out, result.stdout.encode()[:limit].decode('utf-8', 'replace'),
                          result.stderr.encode()[:limit].decode('utf-8', 'replace'),
                          len(result.stdout.encode()) > limit, len(result.stderr.encode()) > limit,
                          int((time.monotonic() - started) * 1000))
    finally:
        (base / challenge).unlink(missing_ok=True)
        if sandbox is not None:
            await asyncio.shield(sandbox.kill())
