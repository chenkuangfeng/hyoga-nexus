"""GA MixinSession sticky fallback/spring-back translated to request-local async models."""
import time
from nexus_core.runtime import RuntimeFault
from .retry import RETRYABLE


class RoutedModel:
    """Route complete request histories; never mix pieces of a response from two suppliers.

    Every model factory is responsible for current authorization and credential resolution.
    Failed partial streams only choose another node for the *next* request. Successfully
    completed tools are outside this module and cannot be replayed by route selection.
    """
    def __init__(self, factories, *, spring_back_seconds=300, clock=time.monotonic):
        if not factories:
            raise ValueError('At least one model is required')
        self.factories, self.spring, self.clock = tuple(factories), spring_back_seconds, clock
        self.current, self.switched_at = 0, 0
        self._clients = []

    async def stream(self, request):
        if self.current and self.clock() - self.switched_at >= self.spring:
            self.current = 0
        base = self.current
        for offset in range(len(self.factories)):
            index = (base + offset) % len(self.factories)
            model = self.factories[index]()
            self._clients.append(model)
            emitted = False
            try:
                async for chunk in model.stream(request):
                    emitted |= chunk.kind in ('text', 'tool_call', 'done')
                    yield chunk
                self.current = index
                if index != base:
                    self.switched_at = self.clock()
                return
            except RuntimeFault as exc:
                if emitted:
                    self.current = (index + 1) % len(self.factories)
                    self.switched_at = self.clock()
                    raise
                if exc.code not in RETRYABLE or offset == len(self.factories) - 1:
                    raise
            finally:
                await model.close()
                self._clients.remove(model)

    async def close(self):
        for model in tuple(self._clients):
            await model.close()
        self._clients.clear()
