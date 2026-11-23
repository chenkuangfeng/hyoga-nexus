"""E2B-compatible gateway adapters with bounded per-session file transfer and durable cleanup."""
from __future__ import annotations

import asyncio
import hashlib
import json
import tempfile
import logging
from dataclasses import asdict
from pathlib import Path

import httpx
from e2b import AsyncSandbox
from e2b.exceptions import SandboxException
from e2b.sandbox.sandbox_api import SandboxQuery

from nexus_core.sandbox import ExecResult, SandboxError
from .backends.remote import MAX_MESSAGE, decode_result
from .lifecycle import Journal, drain
from .remote_runner import Execution
from .settings import SandboxSettings
from .transfer import MAX_TOTAL_BYTES, ROOTS, pack, publish, recover_publication

logger = logging.getLogger(__name__)


def provider_options(config: dict) -> dict:
    """Resolve a credential reference at use time, without exporting it into the VM."""
    template, token_file, domain = (config.get(key) for key in ('template', 'api_key_file', 'domain'))
    if (not isinstance(template, str) or not template or (not config.get('api_key') and (not isinstance(token_file, str)
            or not Path(token_file).is_absolute())) or not isinstance(domain, str) or not domain
            or any(char not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-' for char in domain)
            or not isinstance(config.get('revision'), str) or not config['revision'].strip()):
        raise SandboxError('sandbox_provider_configuration_invalid')
    try:
        key = config.get('api_key')
        if key is None:
            with Path(token_file).open() as stream:
                key = stream.read(1025).strip()
        if not isinstance(key, str) or not key or len(key) > 1024:
            raise ValueError
    except (OSError, ValueError):
        raise SandboxError('sandbox_provider_configuration_invalid') from None
    return {'api_key': key, 'domain': domain, 'request_timeout': 30}


def provider_identity(config: dict) -> str:
    """Hash immutable template identity and the operator's policy revision, excluding secrets."""
    material = {key: config.get(key) for key in ('type', 'template', 'domain', 'revision')}
    return hashlib.sha256(json.dumps(material, sort_keys=True).encode()).hexdigest()


async def download(sandbox, remote: str, destination: Path, limit: int) -> None:
    """Stream from the authenticated provider file API, stopping before exceeding the local limit.

    E2B 2.3.0 files.read(format='stream') buffers the HTTP response first, so this adapter uses the
    public envd endpoint and sandbox headers with an independent streaming client. Tokens stay in
    headers so ordinary HTTP request logging cannot expose a signed query string.
    """
    url = f'{sandbox.envd_api_url}/files'
    async with httpx.AsyncClient(trust_env=False, follow_redirects=False, timeout=30) as client:
        async with client.stream('GET', url, params={'path': remote, 'username': 'user'},
                                 headers=sandbox.connection_config.sandbox_headers) as response:
            response.raise_for_status()
            total = 0
            with destination.open('wb') as stream:
                async for chunk in response.aiter_bytes(chunk_size=65536):
                    total += len(chunk)
                    if total > limit:
                        raise SandboxError('sandbox_transfer_limit_exceeded')
                    stream.write(chunk)


async def recover_provider(record: dict, config: dict, journal: Journal) -> None:
    """Destroy known instances, or discover an unknown create result through request metadata."""
    options = provider_options(config)
    if record.get('policy') != provider_identity(config):
        raise SandboxError('sandbox_cleanup_policy_changed')
    ids = [record['sandbox_id']] if record.get('sandbox_id') else []
    if not ids:
        paginator = AsyncSandbox.list(query=SandboxQuery(metadata={'nexus_request': record['id']}), **options)
        while paginator.has_next:
            ids.extend(item.sandbox_id for item in await paginator.next_items())
    for sandbox_id in ids:
        await AsyncSandbox.kill(sandbox_id, **options)
    # An uncertain create can still complete after a discovery request. Keep it pending through the VM TTL.
    if record.get('sandbox_id') or record.get('expires_at', 0) < __import__('time').time():
        journal.write(record['id'], state='finished')


async def execute_provider(request: Execution, settings: SandboxSettings, config: dict,
                           *, journal: Journal | None = None) -> ExecResult:
    """Transfer only the current session, run with bounded capture, publish files and destroy the VM."""
    options = provider_options(config)
    if settings.paused or not settings.enabled or request.limits != {
        'cpus': settings.cpus, 'memory_mb': settings.memory_mb, 'pids': settings.pids,
    } or request.timeout_seconds > max(settings.exec_timeout_max_seconds, settings.skill_timeout_max_seconds):
        raise SandboxError('sandbox_remote_policy_mismatch')
    base = settings.root / request.tenant_id / request.session_id
    base.mkdir(parents=True, exist_ok=True)
    await asyncio.to_thread(recover_publication, base)
    for name in (*ROOTS, 'skills'):
        (base / name).mkdir(parents=True, exist_ok=True)
    from .disk_quota import ensure
    await asyncio.to_thread(ensure, settings, base)
    limit = min(settings.workspace_quota_mb * 1024 * 1024, MAX_TOTAL_BYTES)
    ttl = int(request.timeout_seconds) + 300
    if journal:
        import time
        journal.write(request.id, policy=provider_identity(config), expires_at=time.time() + ttl + 60)
    sandbox = None
    create_task = None
    with tempfile.TemporaryDirectory(prefix='nexus-provider-') as temporary:
        staging = Path(temporary)
        pack({name: base / name for name in (*ROOTS, 'skills')}, staging / 'input.tar', limit=limit)
        try:
            create_task = asyncio.create_task(AsyncSandbox.create(
                template=config['template'], secure=True, allow_internet_access=False, timeout=ttl,
                metadata={'nexus_request': request.id}, **options,
            ))
            sandbox = await asyncio.shield(create_task)
            if journal:
                journal.write(request.id, sandbox_id=sandbox.sandbox_id, state='preparing')
            info = await sandbox.get_info(request_timeout=30)
            if info.cpu_count != settings.cpus or info.memory_mb != settings.memory_mb:
                raise SandboxError('sandbox_remote_policy_mismatch')
            control = f'/tmp/nexus-{request.id}'
            payload = asdict(request) | {'transfer_limit': limit}
            await sandbox.files.write(f'{control}/request.json', json.dumps(payload), user='root')
            for filename, source in {
                'runner.py': Path(__file__).with_name('provider_runner.py'),
                'nexus_transfer.py': Path(__file__).with_name('transfer.py'),
                'nexus_output.py': Path(__file__).parent / 'backends' / 'output.py',
            }.items():
                await sandbox.files.write(f'{control}/{filename}', source.read_bytes(), user='root')
            with (staging / 'input.tar').open('rb') as stream:
                await sandbox.files.write(f'{control}/input.tar', stream, user='root')
            await sandbox.commands.run(f'python3 {control}/runner.py {control} prepare', user='root', timeout=30)
            # Refuse templates that grant the execution account root through passwordless sudo.
            await sandbox.commands.run('test "$(id -u)" != 0 && ! sudo -n true 2>/dev/null',
                                       user='user', timeout=10)
            handle = await sandbox.commands.run(f'exec python3 {control}/runner.py {control}',
                                                user='user', background=True,
                                                timeout=request.timeout_seconds + 90)
            waiting = asyncio.create_task(handle.wait())
            if journal:
                journal.write(request.id, state='running')

            async def synchronize():
                await download(sandbox, f'{control}/output.tar', staging / 'output.tar',
                               limit + 4096 * 2048 + 10240)
                await asyncio.to_thread(publish, staging / 'output.tar', base, limit=limit)

            try:
                await asyncio.shield(waiting)
            except asyncio.CancelledError:
                async def stop_and_sync():
                    try:
                        await sandbox.commands.run(f'kill -TERM {int(handle.pid)}', user='root', timeout=10)
                        await asyncio.wait_for(asyncio.shield(waiting), 20)
                        await synchronize()
                    except Exception:
                        logger.warning('Partial sandbox files could not be synchronized for %s', request.id)
                    finally:
                        if not waiting.done():
                            waiting.cancel()
                            await asyncio.gather(waiting, return_exceptions=True)
                await drain(stop_and_sync())
                raise
            await download(sandbox, f'{control}/result.json', staging / 'result.json', MAX_MESSAGE)
            result = decode_result((staging / 'result.json').read_bytes(), request.output_limit)
            await synchronize()
            return result
        except (ValueError, httpx.HTTPError, SandboxException):
            raise SandboxError('sandbox_provider_transfer_failed') from None
        finally:
            async def cleanup():
                nonlocal sandbox
                if journal:
                    journal.write(request.id, state='cleanup_pending')
                if sandbox is None and create_task is not None:
                    try:
                        sandbox = await create_task
                    except Exception:
                        return  # recovery discovers an uncertain create; never retry the command
                    if journal:
                        journal.write(request.id, sandbox_id=sandbox.sandbox_id)
                if sandbox is not None:
                    await sandbox.kill(request_timeout=30)
                    if journal:
                        journal.write(request.id, state='finished')
            await drain(cleanup())
