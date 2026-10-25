"""Cooperative cancellation shared by model, backoff and tool boundaries."""
import asyncio
from typing import Awaitable, TypeVar
from nexus_core.runtime import CancellationTokenPort, RuntimeFault
T = TypeVar('T')

class CancellationToken:
    def __init__(self):
        self._event = asyncio.Event()

    def cancel(self):
        self._event.set()

    def check(self):
        if self._event.is_set():
            raise RuntimeFault('cancelled')

    async def wait(self):
        await self._event.wait()


async def cancellable(operation: Awaitable[T], token: CancellationTokenPort) -> T:
    task = asyncio.ensure_future(operation)
    cancelled = asyncio.create_task(token.wait())
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
