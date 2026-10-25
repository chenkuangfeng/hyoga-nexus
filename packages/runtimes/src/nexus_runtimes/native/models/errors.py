"""Bounded model failures; no vendor bodies or SDK types cross the adapter boundary.

Behavior mapping: GenericAgent llmcore.py and WeKnora models/api/endpoint.go
at revisions a9a36b4 (GenericAgent) and e1f9a6166 (WeKnora). Retry differences are documented.
"""
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import math
import httpx

from nexus_core.runtime import RuntimeFault

RETRYABLE = {'model_timeout', 'model_rate_limited', 'model_provider_unavailable'}
ERROR_BODY_LIMIT = 65536


class ModelFault(RuntimeFault):
    """Internal retry metadata, never included in public exception text.

    output_started survives buffering wrappers. retry_after is a vendor minimum wait;
    recovery_blocked prevents an outer retry layer bypassing an excessive wait.
    """
    def __init__(self, code, *, retry_after=None, output_started=False, recovery_blocked=False):
        super().__init__(code)
        self.retry_after = retry_after
        self.output_started = output_started
        self.recovery_blocked = recovery_blocked


def retry_after(value, *, now=None):
    """Parse seconds or HTTP date; absent/invalid/past values use normal backoff."""
    if not isinstance(value, str) or len(value) > 128:
        return None
    try:
        delay = float(value)
    except ValueError:
        try:
            at = parsedate_to_datetime(value)
            if at.tzinfo is None:
                at = at.replace(tzinfo=timezone.utc)
            delay = at.timestamp() - (now if now is not None else datetime.now(timezone.utc).timestamp())
        except (ValueError, TypeError, OverflowError):
            return None
    return delay if math.isfinite(delay) and delay > 0 else None


def failure(value=None, *, status=None, headers=None):
    """Classify allowlisted structured codes, never free-form messages or secrets."""
    error = value.get('error', value) if isinstance(value, dict) else {}
    error = error if isinstance(error, dict) else {}
    codes = [error.get('code'), error.get('type')]
    mapping = {
        'context_length_exceeded': 'model_context_exceeded',
        'insufficient_quota': 'model_quota_exhausted',
        'authentication_error': 'model_authentication_failed',
        'invalid_api_key': 'model_authentication_failed',
        'permission_error': 'model_authentication_failed',
        'invalid_request_error': 'model_request_rejected',
        'rate_limit_error': 'model_rate_limited',
        'rate_limit_exceeded': 'model_rate_limited',
        'overloaded_error': 'model_provider_unavailable',
        'server_error': 'model_provider_unavailable',
    }
    # Permanent structured classifications take precedence over transient HTTP codes.
    classified = [mapping[c] for c in codes if isinstance(c, str) and c in mapping]
    permanent = next((c for c in classified if c not in RETRYABLE), None)
    if permanent:
        code = permanent
    elif status in (401, 403):
        code = 'model_authentication_failed'
    elif status is not None and status not in (408, 429, 500, 502, 503, 504):
        code = 'model_request_rejected'
    elif classified:
        code = classified[0]
    elif status == 429:
        code = 'model_rate_limited'
    elif status in (408, 500, 502, 503, 504):
        code = 'model_provider_unavailable'
    else:
        code = 'model_response_failed'
    return ModelFault(code, retry_after=retry_after(headers.get('retry-after')) if headers else None)


def mark_output(exc, started):
    """Preserve a stable fault while annotating output hidden by a protocol wrapper."""
    if isinstance(exc, ModelFault):
        exc.output_started |= started
        return exc
    return ModelFault(exc.code, output_started=started)


class _ErrorStream(httpx.AsyncByteStream):
    """Limit bytes before the SDK materializes a rejected response body."""
    def __init__(self, stream):
        self.stream = stream

    async def __aiter__(self):
        remaining = ERROR_BODY_LIMIT
        try:
            async for part in self.stream:
                yield part[:remaining]
                remaining -= min(len(part), remaining)
                if not remaining:
                    break
        finally:
            await self.stream.aclose()

    async def aclose(self):
        await self.stream.aclose()


async def bound_error_response(response):
    """HTTPX response hook: bound streaming error bodies before SDK decoding."""
    if not 200 <= response.status_code < 300 and not response.is_stream_consumed:
        response.stream = _ErrorStream(response.stream)
