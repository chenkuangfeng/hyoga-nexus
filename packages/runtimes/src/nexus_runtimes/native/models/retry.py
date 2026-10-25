"""Cancellable bounded recovery; tools and partial responses are never replayed."""
import asyncio
from contextlib import aclosing
from nexus_core.runtime import RuntimeFault
from .errors import RETRYABLE, mark_output


async def wait_for_retry(exc, default_delay, maximum):
    """Honor the vendor's minimum; never shorten Retry-After to fit a local cap.

    The enclosing model timeout/Run budget cancels this await when its remaining
    time expires. Mark oversized waits so outer recovery layers cannot bypass them.
    """
    delay = getattr(exc, 'retry_after', None)
    if delay is not None and delay > maximum:
        exc.recovery_blocked = True
        raise exc
    await asyncio.sleep(delay if delay is not None else min(maximum, default_delay))


class RetryModel:
    """Retry only pre-output typed transient failures, inside the request deadline."""
    def __init__(self, model, policy):
        self.model, self.policy = model, policy

    async def stream(self, request):
        for attempt in range(self.policy.model_retries + 1):
            emitted = False
            try:
                async with aclosing(self.model.stream(request)) as stream:
                    async for chunk in stream:
                        emitted |= chunk.kind in ('text', 'tool_call', 'done')
                        yield chunk
                return
            except RuntimeFault as original:
                exc = mark_output(original, emitted)
                if (exc.output_started or exc.recovery_blocked or exc.code not in RETRYABLE
                        or attempt == self.policy.model_retries):
                    raise exc from None
                await wait_for_retry(exc, self.policy.retry_delay_seconds * (2 ** attempt),
                                     self.policy.max_retry_delay_seconds)

    async def close(self):
        await self.model.close()
