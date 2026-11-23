"""Standalone authenticated gateway for execution nodes with a shared sandbox workspace.

Run as a single ASGI process behind HTTPS. Keep this entry point separate from the platform API.
"""
from __future__ import annotations

import asyncio
import hmac
import time
from contextlib import suppress
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response

from nexus_core.deployment import section
from nexus_core.sandbox import SandboxError
from nexus_sandbox.backends.remote import MAX_REQUEST
from nexus_sandbox.remote_runner import REQUEST_ID, execute, parse_execution
from nexus_sandbox.settings import apply_profile_policy, load_config
from nexus_sandbox.gateway_state import GatewayState
from nexus_sandbox.lifecycle import drain


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load operator provisioning and drain running commands on graceful shutdown."""
    config = section('sandbox_gateway')
    token_file = Path(config.get('token_file', ''))
    profiles = config.get('profiles', [])
    if (not token_file.is_absolute() or not isinstance(profiles, list) or not profiles
            or not all(isinstance(profile, str) for profile in profiles)):
        raise RuntimeError('sandbox gateway requires token_file and profiles')
    with token_file.open(encoding='utf-8') as stream:
        token = stream.read(1025).strip()
    if not 32 <= len(token) <= 1024 or not all(33 <= ord(char) <= 126 for char in token):
        raise RuntimeError('invalid sandbox gateway token')
    deployment = load_config()
    selected = {item: deployment.profiles.get(item) for item in profiles}
    if not deployment.enabled or any(
        value is None or value.backend != 'docker' or value.network != 'none' for value in selected.values()
    ):
        raise RuntimeError('sandbox gateway profiles must be enabled, network-isolated Docker profiles')
    providers = config.get('providers', {})
    if not isinstance(providers, dict) or any(
        name not in selected or not isinstance(value, dict) or value.get('type') not in ('e2b', 'cubesandbox')
        for name, value in providers.items()
    ):
        raise RuntimeError('invalid sandbox gateway providers')
    root = Path(config.get('state_root', str(deployment.workspace_root) + '/_gateway_state'))
    from nexus_api.gateway_provider_config import load_providers
    providers = load_providers(root, selected, providers)
    state = GatewayState(root, selected, providers)
    await state.recover(set())
    app.state.runtime = state
    app.state.providers = providers
    app.state.token = token.encode()
    app.state.profiles = selected
    app.state.active = {}
    app.state.cancelled = {}
    reaper = asyncio.create_task(state.reaper(app.state.active))
    try:
        yield
    finally:
        tasks = list(app.state.active.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await drain(asyncio.gather(*tasks, return_exceptions=True))
        reaper.cancel()
        with suppress(asyncio.CancelledError):
            await reaper
        state.journal.close()


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


def _authorize(request: Request) -> None:
    expected = b'Bearer ' + request.app.state.token
    if not hmac.compare_digest(request.headers.get('authorization', '').encode(), expected):
        raise HTTPException(401)


@app.post('/v1/executions')
async def run_command(request: Request) -> dict:
    """Validate credentials and the requested execution policy before starting a sandbox."""
    _authorize(request)
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_REQUEST:
            raise HTTPException(413)
    try:
        execution = parse_execution(bytes(body))
    except SandboxError:
        raise HTTPException(400) from None
    state = request.app.state
    settings = state.profiles.get(execution.profile)
    if settings is None:
        raise HTTPException(404)
    settings = apply_profile_policy(settings)
    capabilities = await state.runtime.capabilities(execution.profile, settings)
    if execution.policy_digest != capabilities['policy_digest']:
        raise HTTPException(409, 'sandbox_remote_policy_mismatch')
    if execution.id in state.active or state.cancelled.get(execution.id, 0) > time.monotonic():
        raise HTTPException(409)
    if len(state.active) >= 32:
        raise HTTPException(429)
    try:
        state.runtime.reserve(execution)
    except SandboxError:
        raise HTTPException(409) from None
    provider = state.providers.get(execution.profile)
    if provider is None:
        task = asyncio.create_task(state.runtime.execute_docker(execution, settings, execute))
    else:
        task = asyncio.create_task(state.runtime.execute_provider(execution, settings, provider))
    state.active[execution.id] = task
    try:
        return asdict(await task)
    except asyncio.CancelledError:
        raise HTTPException(409) from None
    except SandboxError:
        raise HTTPException(502) from None
    finally:
        state.active.pop(execution.id, None)


@app.delete('/v1/executions/{request_id}', status_code=204)
async def cancel_command(request_id: str, request: Request) -> Response:
    """Cancel and wait for teardown. Retain a short tombstone for an in-flight POST."""
    _authorize(request)
    if not REQUEST_ID.fullmatch(request_id):
        raise HTTPException(404)
    state = request.app.state
    now = time.monotonic()
    state.cancelled = {key: expiry for key, expiry in state.cancelled.items() if expiry > now}
    task = state.active.get(request_id)
    if len(state.cancelled) >= 4096 and request_id not in state.cancelled and task is None:
        raise HTTPException(429)
    state.cancelled[request_id] = now + 60
    if task is not None:
        if not task.cancelling():
            task.cancel()
        result, = await asyncio.gather(asyncio.shield(task), return_exceptions=True)
        if isinstance(result, Exception):
            raise HTTPException(502)
    return Response(status_code=204)


@app.get('/v1/profiles/{name}/capabilities')
async def capabilities(name: str, request: Request) -> dict:
    """Authenticate and report actual execution identity without starting user code."""
    _authorize(request)
    state = request.app.state
    settings = state.profiles.get(name)
    if settings is None:
        raise HTTPException(404)
    try:
        result = await state.runtime.capabilities(name, apply_profile_policy(settings))
    except SandboxError:
        raise HTTPException(503) from None
    return result


@app.get('/v1/executions/{request_id}')
async def execution_status(request_id: str, request: Request) -> dict:
    """Expose only lifecycle state, allowing cancellation and crash recovery to be verified."""
    _authorize(request)
    if not REQUEST_ID.fullmatch(request_id):
        raise HTTPException(404)
    record = request.app.state.runtime.journal.get(request_id)
    if record is None:
        raise HTTPException(404)
    return {'id': request_id, 'state': record['state']}


@app.get('/v1/profiles/{name}/executions')
async def profile_executions(name: str, request: Request) -> dict:
    """List unfinished cleanup records without exposing commands, users or filesystem paths."""
    _authorize(request)
    runtime = request.app.state.runtime
    if name not in runtime.profiles:
        raise HTTPException(404)
    return {'items': [
        {key: record.get(key) for key in ('id', 'state', 'created_at', 'updated_at')}
        for record in runtime.journal.pending() if record['profile'] == name
    ][:100]}


@app.post('/v1/profiles/{name}/executions/{request_id}/cleanup')
async def retry_cleanup(name: str, request_id: str, request: Request) -> dict:
    """Retry a failed cleanup only after the original request has left the active registry."""
    _authorize(request)
    state = request.app.state
    record = state.runtime.journal.get(request_id) if REQUEST_ID.fullmatch(request_id) else None
    if record is None or record['profile'] != name:
        raise HTTPException(404)
    if request_id in state.active:
        raise HTTPException(409)
    await state.runtime.recover(set(state.active))
    record = state.runtime.journal.get(request_id)
    return {'id': request_id, 'state': record['state']}


@app.get('/v1/profiles/{name}/provider')
async def read_provider(name: str, request: Request) -> dict:
    """Return provider settings with credential presence only."""
    from nexus_api.gateway_provider_config import public_provider
    _authorize(request)
    if name not in request.app.state.profiles:
        raise HTTPException(404)
    return public_provider(request.app.state.providers.get(name))


@app.put('/v1/profiles/{name}/provider')
async def update_provider(name: str, request: Request) -> dict:
    """Update encrypted provider settings after all outstanding instances have been reclaimed."""
    from nexus_api.gateway_provider_config import public_provider, save_provider
    _authorize(request)
    state = request.app.state
    if name not in state.profiles:
        raise HTTPException(404)
    if any(record['profile'] == name for record in state.runtime.journal.pending()):
        raise HTTPException(409, 'sandbox_instances_pending')
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 16384:
            raise HTTPException(413)
    try:
        import json
        config = save_provider(state.runtime.journal.root, name, json.loads(body), state.providers.get(name))
    except (SandboxError, ValueError):
        raise HTTPException(422, 'sandbox_provider_configuration_invalid') from None
    state.providers[name] = config
    return public_provider(config)
