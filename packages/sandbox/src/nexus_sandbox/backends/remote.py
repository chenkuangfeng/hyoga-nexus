"""Execute in an operator-provisioned Linux sandbox over SSH or the Nexus HTTPS gateway.

File tools, skill projections and artifacts use the shared workspace volume. Neither transport receives
host paths. A gateway request ID identifies an execution for cancellation and is never chosen by a model.
"""
from __future__ import annotations

import asyncio
import json
from uuid import uuid4

import httpx

from nexus_core.sandbox import ExecResult, SandboxError
from ..settings import SandboxSettings
from .output import feed_stdin

MAX_MESSAGE = 4 * 1024 * 1024
MAX_REQUEST = 1024 * 1024
MAX_OUTPUT = 200_000


async def read_message(reader: asyncio.StreamReader, limit: int) -> bytes:
    """Read a bounded protocol message, including from a peer that omits its length."""
    chunks = bytearray()
    while part := await reader.read(min(65536, limit + 1 - len(chunks))):
        chunks.extend(part)
        if len(chunks) > limit:
            raise SandboxError('sandbox_remote_response_invalid')
    return bytes(chunks)


def decode_result(raw: bytes, limit: int) -> ExecResult:
    """Validate a remote result before exposing it to tools."""
    try:
        data = json.loads(raw)
        result = ExecResult(**data)
        if (result.exit_code is not None and type(result.exit_code) is not int
                or type(result.duration_ms) is not int or result.duration_ms < 0
                or any(type(item) is not bool for item in (result.timed_out, result.stdout_truncated,
                                                           result.stderr_truncated))
                or any(not isinstance(item, str) or len(item.encode()) > 3 * limit + 128
                       for item in (result.stdout, result.stderr))):
            raise ValueError
        return result
    except (TypeError, ValueError, RecursionError):
        raise SandboxError('sandbox_remote_response_invalid') from None


class RemoteExecutor:
    """Command port for an SSH runner or an authenticated HTTPS gateway."""

    supports_background = False
    skills_mount = '/skills'
    outputs_path = '/outputs'

    def __init__(self, settings: SandboxSettings, tenant_id: str, session_id: str):
        self.settings = settings
        self.tenant_id, self.session_id = tenant_id, session_id
        self.last_cancel_confirmed = False

    def ssh_arguments(self) -> list[str]:
        """Use only the deployment-specified credentials and strictly pinned host keys."""
        settings = self.settings
        return ['ssh', '-F', '/dev/null', '-T', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10',
                '-o', 'StrictHostKeyChecking=yes', '-o', 'GlobalKnownHostsFile=/dev/null',
                '-o', f'UserKnownHostsFile={settings.ssh_known_hosts}', '-o', 'ClearAllForwardings=yes',
                '-o', 'IdentitiesOnly=yes', '-o', 'IdentityAgent=none', '-i', settings.ssh_identity_file,
                '-p', str(settings.ssh_port), '-l', settings.ssh_user, '--', settings.ssh_host,
                'python3', '-m', 'nexus_sandbox.remote_runner']

    async def _ssh(self, payload: str, timeout: float) -> bytes:
        try:
            process = await asyncio.create_subprocess_exec(
                *self.ssh_arguments(), stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
        except OSError:
            raise SandboxError('sandbox_backend_unavailable') from None
        try:
            _, result, code = await asyncio.wait_for(asyncio.gather(
                feed_stdin(process, payload), read_message(process.stdout, MAX_MESSAGE), process.wait(),
            ), timeout)
        finally:
            if process.returncode is None:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
                await process.wait()
        if code != 0:
            raise SandboxError('sandbox_backend_unavailable')
        return result

    def _token(self) -> str:
        try:
            with open(self.settings.token_file, encoding='utf-8') as stream:
                token = stream.read(1025).strip()
            if not token or len(token) > 1024 or not all(33 <= ord(char) <= 126 for char in token):
                raise ValueError
            return token
        except (OSError, ValueError):
            raise SandboxError('sandbox_backend_unavailable') from None

    async def _managed(self, payload: str, timeout: float, request_id: str) -> bytes:
        base = f'{self.settings.endpoint}/v1/executions'
        headers = {'Authorization': f'Bearer {self._token()}'}
        async with httpx.AsyncClient(headers=headers, follow_redirects=False, trust_env=False,
                                     timeout=httpx.Timeout(10, read=timeout)) as client:
            try:
                async with asyncio.timeout(timeout), client.stream(
                    'POST', base, content=payload, headers={'Content-Type': 'application/json'},
                ) as response:
                    response.raise_for_status()
                    body = bytearray()
                    async for chunk in response.aiter_bytes(chunk_size=65536):
                        body.extend(chunk)
                        if len(body) > MAX_MESSAGE:
                            raise SandboxError('sandbox_remote_response_invalid')
                    return bytes(body)
            except (asyncio.CancelledError, TimeoutError, httpx.TransportError, SandboxError):
                self.last_cancel_confirmed = False
                try:
                    async with asyncio.timeout(5), client.stream('DELETE', f'{base}/{request_id}') as response:
                        response.raise_for_status()
                        self.last_cancel_confirmed = response.status_code == 204
                except (httpx.HTTPError, TimeoutError):
                    pass
                raise

    async def run(self, command: str, *, cwd: str, timeout_seconds: float, output_limit: int,
                  env: dict[str, str] | None = None, stdin: str | None = None) -> ExecResult:
        """Execute a validated session command with a separate transport deadline."""
        settings = self.settings
        limit = min(output_limit, MAX_OUTPUT)
        request_id = uuid4().hex
        payload = json.dumps({
            'id': request_id, 'profile': settings.remote_profile,
            'tenant_id': self.tenant_id, 'session_id': self.session_id, 'command': command, 'cwd': cwd,
            'timeout_seconds': timeout_seconds, 'output_limit': limit, 'env': env, 'stdin': stdin,
            'network': settings.network,
            'limits': {'cpus': settings.cpus, 'memory_mb': settings.memory_mb, 'pids': settings.pids}
            if settings.backend == 'managed' else None,
        })
        if len(payload.encode()) > MAX_REQUEST:
            raise SandboxError('sandbox_remote_request_too_large')
        try:
            if settings.backend == 'ssh':
                raw = await self._ssh(payload, timeout_seconds + 15)
            else:
                raw = await self._managed(payload, timeout_seconds + 30, request_id)
        except (TimeoutError, httpx.HTTPError):
            raise SandboxError('sandbox_backend_unavailable') from None
        return decode_result(raw, limit)

    async def close(self) -> None:
        """Each remote request owns its execution lifetime."""
