"""GA cancellable backoff with the WeKnora rule that tools are never replayed by retry."""
import asyncio
from nexus_core.runtime import RuntimeFault

RETRYABLE = {'model_timeout', 'model_rate_limited', 'model_provider_unavailable'}


class RetryModel:
    """Retry only a response that has emitted no text/tool output; cancellation aborts sleep."""
    def __init__(self, model, policy):
        self.model, self.policy = model, policy

    async def stream(self, request):
        for attempt in range(self.policy.model_retries + 1):
            emitted = False
            try:
                async for chunk in self.model.stream(request):
                    emitted |= chunk.kind in ('text', 'tool_call', 'done')
                    yield chunk
                return
            except RuntimeFault as exc:
                if emitted or exc.code not in RETRYABLE or attempt == self.policy.model_retries:
                    raise
                await asyncio.sleep(min(self.policy.max_retry_delay_seconds, self.policy.retry_delay_seconds * (2 ** attempt)))

    async def close(self):
        await self.model.close()
