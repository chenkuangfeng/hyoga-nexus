"""Standalone authenticated gateway for execution nodes with a shared sandbox workspace.

Run as a single ASGI process behind HTTPS. Keep this entry point separate from the platform API.
"""
from __future__ import annotations

import asyncio
import hmac
import time
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response

from nexus_core.deployment import section
from nexus_core.sandbox import SandboxError
from nexus_sandbox.backends.remote import MAX_REQUEST
from nexus_sandbox.remote_runner import REQUEST_ID, execute, parse_execution
from nexus_sandbox.settings import load_config


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
    app.state.providers = providers
    app.state.token = token.encode()
    app.state.profiles = selected
    app.state.active = {}
    app.state.cancelled = {}
    try:
        yield
    finally:
        tasks = list(app.state.active.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


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
    if execution.id in state.active or state.cancelled.get(execution.id, 0) > time.monotonic():
        raise HTTPException(409)
    if len(state.active) >= 32:
        raise HTTPException(429)
    provider = state.providers.get(execution.profile)
    if provider is None:
        task = asyncio.create_task(execute(execution, settings, backend='docker'))
    else:
        from nexus_sandbox.providers import execute_provider
        task = asyncio.create_task(execute_provider(execution, settings, provider))
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
