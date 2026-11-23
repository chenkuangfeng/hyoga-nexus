"""Trusted execution entry point for Linux SSH hosts and the Nexus gateway."""
from __future__ import annotations

import asyncio
import json
import math
import re
import signal
import sys
from dataclasses import asdict, dataclass

from nexus_core.sandbox import ExecResult, SandboxError

from . import paths
from .backends.docker import DockerBackend
from .backends.remote import MAX_OUTPUT, MAX_REQUEST
from .manager import SandboxManager
from .settings import PROFILE_NAME, SandboxSettings, load_settings

REQUEST_ID = re.compile(r'[a-f0-9]{32}')
_SCOPE_ID = re.compile(r'[A-Za-z0-9_-]{1,64}')


@dataclass(frozen=True)
class Execution:
    """The validated v1 execution request. Scope and target profile come from the worker."""

    id: str
    profile: str
    tenant_id: str
    session_id: str
    command: str
    cwd: str
    timeout_seconds: float
    output_limit: int
    env: dict[str, str] | None
    stdin: str | None
    network: str
    limits: dict[str, float] | None


def parse_execution(raw: bytes) -> Execution:
    """Parse a bounded request without resolving files or starting any execution."""
    try:
        if len(raw) > MAX_REQUEST:
            raise ValueError
        request = Execution(**json.loads(raw))
        if (not REQUEST_ID.fullmatch(request.id) or not PROFILE_NAME.fullmatch(request.profile)
                or not _SCOPE_ID.fullmatch(request.tenant_id) or not _SCOPE_ID.fullmatch(request.session_id)
                or not isinstance(request.command, str) or not request.command.strip() or len(request.command) > 20_000
                or type(request.timeout_seconds) not in (int, float) or not math.isfinite(request.timeout_seconds)
                or not 0 < request.timeout_seconds <= 3600
                or type(request.output_limit) is not int or not 1 <= request.output_limit <= MAX_OUTPUT
                or request.network != 'none'
                or (request.env is not None and (not isinstance(request.env, dict) or len(request.env) > 32))
                or (request.stdin is not None and not isinstance(request.stdin, str))):
            raise ValueError
        paths.split(request.cwd)
        if request.limits is not None:
            if (not isinstance(request.limits, dict) or set(request.limits) != {'cpus', 'memory_mb', 'pids'}
                    or any(type(value) not in (int, float) or not math.isfinite(value)
                           for value in request.limits.values())):
                raise ValueError
        return request
    except (TypeError, ValueError, AttributeError, OverflowError, RecursionError, SandboxError):
        raise SandboxError('sandbox_remote_request_invalid') from None


async def execute(request: Execution, settings: SandboxSettings, *, backend: str) -> ExecResult:
    """Apply the node's configured policy and remove its per-request execution environment."""
    if not settings.enabled or settings.paused or settings.backend != backend or settings.network != request.network:
        raise SandboxError('sandbox_backend_unavailable')
    if backend == 'docker' and request.limits != {
        'cpus': settings.cpus, 'memory_mb': settings.memory_mb, 'pids': settings.pids,
    }:
        raise SandboxError('sandbox_remote_policy_mismatch')
    maximum = max(settings.exec_timeout_max_seconds, settings.skill_timeout_max_seconds)
    if request.timeout_seconds > maximum:
        raise SandboxError('sandbox_remote_policy_mismatch')
    docker = DockerBackend(settings, lifetime=math.ceil(request.timeout_seconds) + 60) if backend == 'docker' else None
    manager = SandboxManager(settings, docker=docker)
    session = manager.session(
        request.tenant_id, request.session_id, default_timeout=request.timeout_seconds,
        output_limit=request.output_limit, execution_id=request.id,
    )
    try:
        return await session.exec(request.command, cwd=request.cwd, timeout_seconds=request.timeout_seconds,
                                  env=request.env, stdin=request.stdin, max_timeout=maximum)
    finally:
        await manager.release(request.tenant_id, request.session_id)


async def _ssh_main(request: Execution) -> ExecResult:
    if request.limits is not None:
        raise SandboxError('sandbox_remote_request_invalid')
    task = asyncio.create_task(execute(request, load_settings(profile=request.profile), backend='bwrap'))
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGHUP, signal.SIGTERM):
        loop.add_signal_handler(sig, task.cancel)
    return await task


def main() -> int:
    """Accept one request from stdin and emit only its JSON result on stdout."""
    try:
        request = parse_execution(sys.stdin.buffer.read(MAX_REQUEST + 1))
        result = asyncio.run(_ssh_main(request))
        sys.stdout.buffer.write(json.dumps(asdict(result), ensure_ascii=False).encode())
        return 0
    except (Exception, asyncio.CancelledError):
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
