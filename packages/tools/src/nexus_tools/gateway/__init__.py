"""Authorization and persistence injected by the application composition root."""
from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from typing import Protocol

from jsonschema import Draft202012Validator, ValidationError
from nexus_core.runtime import CancellationTokenPort, RuntimeFault, ToolCall, ToolResult
from nexus_tools.registry import ToolContext, ToolRegistry
from nexus_tools.registry.invocation import invoke


class ToolAccessPort(Protocol):
    async def authorize(self, name: str, version: str) -> str: ...
    async def start(self, call: ToolCall, binding_id: str | None) -> str: ...
    async def finish(self, invocation_id: str, status: str, summary: str, error_code: str | None) -> None: ...
    async def denied(self, name: str) -> None: ...


async def _controlled(operation, token):
    task, cancelled = asyncio.ensure_future(operation), asyncio.create_task(token.wait())
    try:
        done, _ = await asyncio.wait((task, cancelled), return_when=asyncio.FIRST_COMPLETED)
        if cancelled in done:
            raise RuntimeFault('cancelled')
        return await task
    finally:
        for pending in (task, cancelled):
            if not pending.done():
                pending.cancel()
        await asyncio.gather(task, cancelled, return_exceptions=True)


class AuthorizedToolGateway:
    def __init__(self, registry: ToolRegistry, access: ToolAccessPort,
                 bindings: dict[str, str], *, run_id: str, session_id: str, workspace_id: str):
        self.registry, self.access, self.bindings = registry, access, bindings
        self.run_id, self.session_id, self.workspace_id = run_id, session_id, workspace_id

    async def definitions(self):
        output = []
        for name, version in self.bindings.items():
            tool = self.registry.get(name, version)
            if tool and tool.definition.capability == 'python_function':
                try:
                    await self.access.authorize(name, version)
                except RuntimeFault:
                    continue
                output.append(tool.definition)
        return tuple(output)

    async def execute(self, call: ToolCall, cancellation: CancellationTokenPort) -> ToolResult:
        cancellation.check()
        version = self.bindings.get(call.name)
        tool = self.registry.get(call.name, version) if version else None
        binding_id = None
        error = None
        if tool is None:
            error = 'tool_not_registered'
        elif tool.definition.capability != 'python_function':
            error = 'sandbox_unavailable'
        else:
            try:
                binding_id = await self.access.authorize(call.name, version)
            except RuntimeFault:
                error = 'tool_authorization_denied'
        if error:
            await self.access.denied(call.name)
        if not error and tool.definition.requires_approval:
            if not hasattr(self.access, 'approval'):
                return ToolResult('Action approval is unavailable', error_code='tool_approval_unavailable')
            decision = await self.access.approval(call)
            if isinstance(decision, ToolResult):
                return decision
            call = replace(call, arguments=decision)
        invocation_id = await self.access.start(call, binding_id)
        invoked = False
        try:
            if error:
                result = ToolResult(error, error_code=error)
            else:
                try:
                    arguments = json.loads(call.arguments)
                    if not isinstance(arguments, dict):
                        raise ValueError()
                    Draft202012Validator(tool.definition.parameters).validate(arguments)
                except (ValueError, ValidationError, RecursionError):
                    result = ToolResult('tool_arguments_invalid', error_code='tool_arguments_invalid')
                else:
                    context = ToolContext(invocation_id, self.run_id, self.session_id, self.workspace_id, cancellation)
                    invoked = True
                    async with asyncio.timeout(tool.definition.timeout_seconds):
                        async def progress(text):
                            if hasattr(self.access, 'progress'):
                                await self.access.progress(invocation_id, text)
                        result = await _controlled(invoke(tool, arguments, context, progress), cancellation)
                    if not isinstance(result, ToolResult):
                        raise RuntimeFault('tool_result_invalid')
            # The public projection is the only output allowed in events, model context or history.
            public = (result.error_code or 'Tool finished') if error else tool.public_result(result)
            public = str(public)[:4000]
            result = replace(result, data=public, continuation=result.continuation[:2000])
            await self.access.finish(invocation_id, 'failed' if result.error_code else 'completed', public, result.error_code)
            return result
        except (TimeoutError, RuntimeFault, asyncio.CancelledError) as exc:
            uncertain = bool(invoked and tool and tool.definition.side_effects)
            code = 'interrupted' if uncertain else 'tool_timeout' if isinstance(exc, TimeoutError) else getattr(exc, 'code', 'cancelled')
            await self.access.finish(invocation_id, 'interrupted' if uncertain else 'cancelled' if code == 'cancelled' else 'failed', code, code)
            if isinstance(exc, asyncio.CancelledError) and not uncertain:
                raise
            if code in ('cancelled', 'interrupted'):
                raise RuntimeFault(code) from None
            return ToolResult(code, error_code=code)
        except Exception:
            code = 'interrupted' if invoked and tool and tool.definition.side_effects else 'tool_failed'
            await self.access.finish(invocation_id, 'interrupted' if code == 'interrupted' else 'failed', code, code)
            if code == 'interrupted':
                raise RuntimeFault(code) from None
            return ToolResult(code, error_code=code)
