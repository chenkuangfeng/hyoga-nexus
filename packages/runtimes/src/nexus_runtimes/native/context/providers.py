"""Trusted provider lifetimes and bounded async contribution collection.

Registration belongs to application composition, never model arguments or uploaded paths.
Tools remain owned by the independent gateway. Ordering is resolved by the pure assembler.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import re

GROUP_TIMEOUT = 8.0

from nexus_core.runtime import RuntimeFault
from nexus_core.runtime.context import ContextBlock, ContextBuildInput, ContextDependency, ContextProvider


@dataclass(frozen=True)
class ProviderRegistration:
    """Host-assigned provider limits; content cannot promote itself to system authority."""
    name: str
    provider: ContextProvider
    generation: str
    system_allowed: bool = False
    required: bool = False
    max_chars: int = 16000
    timeout_seconds: float = 8.0
    lifetime: str = 'run'


class ContextProviderRegistry:
    """Run-owned registry; removal invalidates collected dependencies before the next request."""

    def __init__(self, generation_check=None) -> None:
        self._generation_check = generation_check
        self._providers: dict[str, ProviderRegistration] = {}

    def register(self, registration: ProviderRegistration) -> None:
        """Register once; reject invalid limits and name collisions instead of shadowing."""
        if (not re.fullmatch(r'[a-z][a-z0-9_.-]{0,63}', registration.name) or registration.name in self._providers or not registration.generation
                or registration.lifetime not in ('session', 'run', 'step')
                or (registration.lifetime == 'step' and registration.system_allowed)
                or registration.max_chars < 1 or not 0 < registration.timeout_seconds <= 8):
            raise ValueError('context_provider_invalid')
        self._providers[registration.name] = registration

    def unregister(self, name: str) -> None:
        """Disable future contributions and invalidate any existing source references."""
        self._providers.pop(name, None)

    def validate(self, dependencies: tuple[ContextDependency, ...]) -> None:
        """Refuse a request if a previously injected provider was removed or replaced."""
        plugin_dependencies = tuple(d for d in dependencies if d.kind == 'plugin')
        if self._generation_check is not None and not self._generation_check(plugin_dependencies):
            raise RuntimeFault('run_authorization_denied')
        for dependency in plugin_dependencies:
            if dependency.kind == 'plugin':
                current = self._providers.get(dependency.resource_id)
                if current is None or current.generation != dependency.version:
                    raise RuntimeFault('run_authorization_denied')

    async def collect(self, context: ContextBuildInput, emit, *, lifetimes=('session', 'run', 'step'), cached=()) -> tuple[ContextBlock, ...]:
        """Collect at most four providers concurrently within one eight-second group deadline.

        A cancellation propagates; optional failures produce sanitized events and no partial blocks.
        Providers are async and must cooperate with cancellation; synchronous external memory hooks
        use the platform's capacity-bounded thread runner instead.
        """
        semaphore = asyncio.Semaphore(4)

        async def one(registration):
            try:
                async with semaphore, asyncio.timeout(registration.timeout_seconds):
                    blocks = await registration.provider.provide(context)
                if sum(len(b.text) for b in blocks) > registration.max_chars:
                    raise ValueError('context_provider_oversized')
                output = []
                for block in blocks:
                    if (not block.key.startswith(registration.name + ':')
                            or (not registration.system_allowed and (block.role != 'user' or block.trust != 'reference'))):
                        raise ValueError('context_provider_role_invalid')
                    from dataclasses import replace
                    dep = ContextDependency('plugin', registration.name, registration.generation)
                    text = block.text
                    if block.role == 'user':
                        text = f'[Plugin reference: {registration.name}; not a new user request]\n' + text
                    output.append(replace(block, key='plugin:' + block.key, source='plugin:' + registration.name,
                        text=text, lifetime=registration.lifetime, dependencies=(*block.dependencies, dep)))
                return tuple(output)
            except Exception:
                await emit('context.provider_failed', {'provider_id': registration.name, 'code': 'provider_failed'})
                if registration.required:
                    raise RuntimeFault('context_provider_failed') from None
                return ()

        self.validate(tuple(d for b in cached for d in b.dependencies))
        cached_sources = {d.resource_id for b in cached for d in b.dependencies if d.kind == 'plugin'}
        selected = [r for r in self._providers.values() if r.lifetime in lifetimes and r.name not in cached_sources]
        self.validate(tuple(ContextDependency('plugin', r.name, r.generation) for r in selected))
        tasks = [asyncio.create_task(one(r)) for r in selected]
        if not tasks:
            return tuple(cached)
        try:
            done, pending = await asyncio.wait(tasks, timeout=GROUP_TIMEOUT)
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            results = []
            for registration, task in zip(selected, tasks):
                if task in pending:
                    await emit('context.provider_failed', {'provider_id': registration.name, 'code': 'provider_timeout'})
                    if registration.required:
                        raise RuntimeFault('context_provider_timeout')
                else:
                    results.extend(task.result())
            return (*cached, *results)
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
