"""Run-local adaptation of GenericAgent plugins/hooks.py (a9a36b4, MIT).

Discovery accepts explicit trusted module names from application composition, never paths or
names from model arguments. Returned transformations are typed and cannot grant tool authority.
"""
from __future__ import annotations
import asyncio
import importlib
from dataclasses import replace
from collections.abc import Awaitable, Callable
from nexus_core.native import HookContext, HookTransform
from nexus_core.runtime import RuntimeFault

Transform = Callable[[HookContext], Awaitable[HookTransform | None]]


class HookRegistry:
    """Own callback lifetimes; isolate failures and return a validated combined transformation."""
    def __init__(self):
        self._callbacks: dict[str, list[Transform]] = {}

    def register(self, event: str, callback: Transform) -> None:
        """Attach a trusted callback once; event names follow HookContext phases."""
        if event not in ('agent.before', 'agent.after', 'turn.before', 'turn.after'):
            raise ValueError('Unknown context hook phase')
        if callback not in self._callbacks.setdefault(event, []):
            self._callbacks[event].append(callback)

    def unregister(self, event: str, callback: Transform) -> None:
        """Remove a callback without affecting another Run's registry."""
        if callback in self._callbacks.get(event, []):
            self._callbacks[event].remove(callback)

    def clear(self, event: str | None = None) -> None:
        """Release one phase or every callback on Run exit."""
        if event:
            self._callbacks.pop(event, None)
        else:
            self._callbacks.clear()

    def load(self, module_names: tuple[str, ...]) -> None:
        """Load operator-approved modules exposing register_hooks(registry); no auto-scan of uploads."""
        for name in module_names:
            importlib.import_module(name).register_hooks(self)

    async def trigger(self, context: HookContext, emit) -> HookTransform:
        """Collect bounded user-context additions; report callback failures without raw diagnostics."""
        messages, prompts = [], []
        for callback in tuple(self._callbacks.get(context.phase, [])):
            try:
                async with asyncio.timeout(1):
                    result = await callback(context)
                if result is None:
                    continue
                if not isinstance(result, HookTransform):
                    raise RuntimeFault('hook_transform_invalid')
                if any(m.role != 'user' or m.tool_calls or m.tool_call_id or len(m.content) > 8000
                       for m in result.append_messages) or sum(len(m.content) for m in result.append_messages) > 16000:
                    raise RuntimeFault('hook_transform_invalid')
                if len(result.done_prompts) > 10 or any(not isinstance(p, str) or len(p) > 2000 for p in result.done_prompts):
                    raise RuntimeFault('hook_transform_invalid')
                source = f'hook:{context.phase}:{callback.__module__}.{getattr(callback, "__qualname__", type(callback).__name__)}'
                messages.extend(replace(message, context_source=f'{source[:180]}:{context.turn}:{index}')
                                for index, message in enumerate(result.append_messages))
                prompts.extend(result.done_prompts)
            except Exception:
                await emit('hook.failed', {'phase': context.phase, 'turn': context.turn})
        return HookTransform(tuple(messages), tuple(prompts))
