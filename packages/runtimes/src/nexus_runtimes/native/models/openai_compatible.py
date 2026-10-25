"""Chat Completions adapter: SDK objects, bodies and exceptions stay inside this module."""
from __future__ import annotations

from typing import AsyncIterator
from urllib.parse import urlsplit
import httpx
from openai import AsyncOpenAI, APIError, APIConnectionError, APIStatusError, APITimeoutError
from nexus_core.runtime import ModelChunk, ModelRequest, RuntimeFault
from .errors import ERROR_BODY_LIMIT, ModelFault, failure, mark_output, bound_error_response
from .usage import usage_chunk
from .protocols.state import finish, validate_calls


class OpenAICompatibleModel:
    """SDK transport with strict terminal validation and SDK retries disabled."""
    def __init__(self, *, model: str, api_key: str, base_url: str = 'https://api.openai.com/v1',
                 timeout: float = 60, http_client=None, options=None):
        parsed = urlsplit(base_url)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise RuntimeFault('model_configuration_invalid')
        self._options = options or {}
        self._model = model
        http_client = http_client or httpx.AsyncClient(timeout=timeout, follow_redirects=False)
        if bound_error_response not in http_client.event_hooks['response']:
            http_client.event_hooks['response'].append(bound_error_response)
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=timeout,
                                   max_retries=0, http_client=http_client)

    async def close(self):
        """Release the SDK and its injected HTTP client."""
        await self._client.close()

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelChunk]:
        """Yield visible text, complete tools, usage and one validated terminal."""
        messages = []
        for message in request.messages:
            item = {'role': message.role, 'content': message.content}
            if message.tool_calls:
                item['tool_calls'] = [{'id': c.id, 'type': 'function',
                    'function': {'name': c.name, 'arguments': c.arguments}} for c in message.tool_calls]
            if message.tool_call_id:
                item['tool_call_id'] = message.tool_call_id
            messages.append(item)
        options = dict(model=self._model, messages=messages, stream=True,
                       max_completion_tokens=request.max_output_tokens,
                       stream_options={'include_usage': True})
        for name in ('temperature', 'reasoning_effort'):
            if name in self._options:
                options[name] = self._options[name]
        if request.tools:
            options['tools'] = [{'type': 'function', 'function': {
                'name': t.name, 'description': t.description, 'parameters': t.parameters}} for t in request.tools]
            options['parallel_tool_calls'] = False
        stream, started = None, False
        try:
            if self._options.get('stream') is False:
                options.pop('stream_options', None); options['stream'] = False
                reply = await self._client.chat.completions.create(**options)
                error = getattr(reply, 'error', None)
                if error is not None:
                    raise failure({'error': error})
                if len(reply.choices) != 1:
                    raise RuntimeFault('model_stream_invalid')
                choice = reply.choices[0]
                raw_calls = [{'id': c.id, 'name': c.function.name, 'arguments': c.function.arguments}
                             for c in choice.message.tool_calls or []]
                if choice.finish_reason == 'stop' and raw_calls or choice.finish_reason == 'tool_calls' and not raw_calls:
                    raise RuntimeFault('model_stream_invalid')
                reason = finish(choice.finish_reason, raw_calls)
                if choice.message.refusal:
                    reason = 'content_filter'
                calls = validate_calls(raw_calls, reason)
                usage = usage_chunk(reply.usage.model_dump(), 'openai_chat_completions') if reply.usage else None
                if choice.message.content:
                    if len(choice.message.content) > request.max_output_tokens * 8:
                        raise RuntimeFault('budget_exhausted')
                    started = True
                    yield ModelChunk('text', text=choice.message.content)
                for call in calls:
                    started = True
                    yield ModelChunk('tool_call', tool_call=call)
                if usage:
                    yield usage
                yield ModelChunk('done', finish_reason=reason)
                return
            stream = await self._client.chat.completions.create(**options)
            calls, reason, last_index, next_index, total_chars = {}, None, None, 0, 0
            by_id, refused = {}, False
            async for chunk in stream:
                if chunk.usage:
                    yield usage_chunk(chunk.usage.model_dump(), 'openai_chat_completions')
                if not chunk.choices:
                    continue
                if len(chunk.choices) != 1 or reason is not None:
                    raise RuntimeFault('model_stream_invalid')
                choice = chunk.choices[0]
                if choice.delta.refusal:
                    refused = True
                if choice.delta.content:
                    total_chars += len(choice.delta.content)
                    if total_chars > request.max_output_tokens * 8:
                        raise RuntimeFault('budget_exhausted')
                    started = True
                    yield ModelChunk('text', text=choice.delta.content)
                for delta in choice.delta.tool_calls or []:
                    index = delta.index
                    if index is None:
                        index = by_id.get(delta.id) if delta.id else last_index
                        if index is None:
                            index = next_index
                    if type(index) is not int or not 0 <= index <= 2**31 - 1:
                        raise RuntimeFault('model_stream_invalid')
                    if delta.id and delta.id in by_id and by_id[delta.id] != index:
                        raise RuntimeFault('model_stream_invalid')
                    last_index, next_index = index, max(next_index, index + 1)
                    if delta.id:
                        by_id[delta.id] = index
                    current = calls.setdefault(index, {'id': '', 'name': '', 'arguments': ''})
                    if delta.id:
                        if current['id'] and current['id'] != delta.id:
                            raise RuntimeFault('model_stream_invalid')
                        current['id'] = delta.id
                    if delta.function:
                        name = delta.function.name or ''
                        if name and current['name'] != name:
                            current['name'] += name
                        current['arguments'] += delta.function.arguments or ''
                        total_chars += len(delta.function.arguments or '')
                    if (len(calls) > 32 or len(current['id']) > 255 or len(current['name']) > 64):
                        raise RuntimeFault('model_stream_invalid')
                if total_chars > request.max_output_tokens * 8:
                    raise RuntimeFault('budget_exhausted')
                if choice.finish_reason:
                    reason = choice.finish_reason
            raw_calls = [calls[k] for k in sorted(calls)]
            if reason == 'stop' and raw_calls or reason == 'tool_calls' and not raw_calls:
                raise RuntimeFault('model_stream_invalid')
            normalized = 'content_filter' if refused else finish(reason, raw_calls)
            for call in validate_calls(raw_calls, normalized):
                started = True
                yield ModelChunk('tool_call', tool_call=call)
            yield ModelChunk('done', finish_reason=normalized)
        except APITimeoutError:
            raise ModelFault('model_timeout', output_started=started) from None
        except APIConnectionError:
            raise ModelFault('model_provider_unavailable', output_started=started) from None
        except APIStatusError as exc:
            # Classify structured fields only. SDK exception bodies never leave this frame.
            body = exc.body if len(exc.response.content) <= ERROR_BODY_LIMIT else None
            raise mark_output(failure(body, status=exc.status_code, headers=exc.response.headers), started) from None
        except APIError as exc:
            raise mark_output(failure(exc.body), started) from None
        except RuntimeFault as exc:
            raise mark_output(exc, started) from None
        except httpx.TimeoutException:
            raise ModelFault('model_timeout', output_started=started) from None
        except httpx.TransportError:
            raise ModelFault('model_provider_unavailable', output_started=started) from None
        except Exception:
            raise ModelFault('model_stream_invalid', output_started=started) from None
        finally:
            if stream is not None:
                await stream.close()
