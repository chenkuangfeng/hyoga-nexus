"""Chat Completions adapter: SDK objects and errors never escape this module."""
from __future__ import annotations

from typing import AsyncIterator
from urllib.parse import urlsplit

from openai import AsyncOpenAI, APIConnectionError, APIStatusError, APITimeoutError, RateLimitError
from nexus_core.runtime import ModelChunk, ModelRequest, RuntimeFault, ToolCall


class OpenAICompatibleModel:
    def __init__(self, *, model: str, api_key: str, base_url: str = 'https://api.openai.com/v1',
                 timeout: float = 60, http_client=None, options=None):
        parsed = urlsplit(base_url)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise RuntimeFault('model_configuration_invalid')
        self._options = options or {}
        self._model = model
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=timeout,
                                   max_retries=0, http_client=http_client)

    async def close(self):
        await self._client.close()

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelChunk]:
        messages = []
        for message in request.messages:
            item = {'role': message.role, 'content': message.content}
            if message.tool_calls:
                item['tool_calls'] = [{'id': call.id, 'type': 'function',
                                       'function': {'name': call.name, 'arguments': call.arguments}}
                                      for call in message.tool_calls]
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
                'name': tool.name, 'description': tool.description, 'parameters': tool.parameters}}
                for tool in request.tools]
            options['parallel_tool_calls'] = False
        stream = None
        try:
            if self._options.get('stream') is False:
                options.pop('stream_options', None); options['stream'] = False
                reply = await self._client.chat.completions.create(**options)
                if len(reply.choices) != 1:
                    raise RuntimeFault('model_stream_invalid')
                choice = reply.choices[0]
                if choice.message.content:
                    yield ModelChunk('text', text=choice.message.content)
                for call in choice.message.tool_calls or []:
                    yield ModelChunk('tool_call', tool_call=ToolCall(call.id, call.function.name, call.function.arguments))
                if reply.usage:
                    yield ModelChunk('usage', total_tokens=reply.usage.total_tokens, usage={'input': reply.usage.prompt_tokens, 'output': reply.usage.completion_tokens})
                yield ModelChunk('done', finish_reason=choice.finish_reason)
                return
            stream = await self._client.chat.completions.create(**options)
            calls: dict[int, dict[str, str]] = {}
            reason = None
            total_chars = 0
            async for chunk in stream:
                if chunk.usage:
                    yield ModelChunk('usage', total_tokens=chunk.usage.total_tokens, usage={'input': chunk.usage.prompt_tokens, 'output': chunk.usage.completion_tokens,
                        'cache_read': getattr(chunk.usage.prompt_tokens_details, 'cached_tokens', 0) or 0})
                if not chunk.choices:
                    continue
                if len(chunk.choices) != 1 or reason is not None:
                    raise RuntimeFault('model_stream_invalid')
                choice = chunk.choices[0]
                if choice.delta.content:
                    total_chars += len(choice.delta.content)
                    yield ModelChunk('text', text=choice.delta.content)
                for delta in choice.delta.tool_calls or []:
                    if delta.index < 0 or delta.index > 31:
                        raise RuntimeFault('model_stream_invalid')
                    current = calls.setdefault(delta.index, {'id': '', 'name': '', 'arguments': ''})
                    if delta.id:
                        current['id'] += delta.id
                    if delta.function:
                        current['name'] += delta.function.name or ''
                        current['arguments'] += delta.function.arguments or ''
                        total_chars += len(delta.function.arguments or '')
                    if len(current['id']) > 255 or len(current['name']) > 100:
                        raise RuntimeFault('model_stream_invalid')
                if total_chars > request.max_output_tokens * 8:
                    raise RuntimeFault('budget_exhausted')
                if choice.finish_reason:
                    reason = choice.finish_reason
            if reason is None or (calls and reason not in ('tool_calls', 'length', 'max_tokens')) or (reason == 'tool_calls' and not calls):
                raise RuntimeFault('model_stream_invalid')
            for _, call in sorted(calls.items()):
                if not call['id'] or not call['name']:
                    raise RuntimeFault('model_stream_invalid')
                yield ModelChunk('tool_call', tool_call=ToolCall(**call))
            yield ModelChunk('done', finish_reason=reason)
        except APITimeoutError:
            raise RuntimeFault('model_timeout') from None
        except RateLimitError:
            raise RuntimeFault('model_rate_limited') from None
        except APIConnectionError:
            raise RuntimeFault('model_provider_unavailable') from None
        except APIStatusError as exc:
            code = 'model_context_exceeded' if exc.code == 'context_length_exceeded' else 'model_provider_unavailable'
            raise RuntimeFault(code) from None
        except RuntimeFault:
            raise
        except Exception:
            raise RuntimeFault('model_stream_invalid') from None
        finally:
            if stream is not None:
                await stream.close()
