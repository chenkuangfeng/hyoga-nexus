"""Responses/Anthropic wire adapters translated from GA llmcore.py (a9a36b4, MIT).

The adapters share HTTP bounds, but preserve each protocol's message blocks, event ordering,
usage, tool argument deltas and terminal status. Only normalized core chunks leave this file.
"""
import json
import httpx
from nexus_core.runtime import ModelChunk, RuntimeFault
from ..errors import ERROR_BODY_LIMIT, ModelFault, failure, mark_output
from ..usage import usage_chunk
from .state import ProtocolState


def anthropic_messages(messages):
    """Convert complete tool exchanges into Anthropic content blocks and merge adjacent roles."""
    system, wire = [], []
    for message in messages:
        if message.role == 'system':
            system.append(message.content); continue
        role = 'assistant' if message.role == 'assistant' else 'user'
        if message.role == 'tool':
            content = [{'type': 'tool_result', 'tool_use_id': message.tool_call_id, 'content': message.content}]
        else:
            content = [{'type': 'text', 'text': message.content}] if message.content.strip() else []
            content.extend({'type': 'tool_use', 'id': call.id, 'name': call.name, 'input': json.loads(call.arguments)} for call in message.tool_calls)
        if not content:
            content = [{'type': 'text', 'text': '.'}]
        if wire and wire[-1]['role'] == role:
            wire[-1]['content'].extend(content)
        else:
            wire.append({'role': role, 'content': content})
    return '\n'.join(system), wire


def responses_messages(messages):
    """Preserve Responses function-call IDs and output items instead of flattening history."""
    result = []
    for message in messages:
        if message.role == 'tool':
            result.append({'type': 'function_call_output', 'call_id': message.tool_call_id, 'output': message.content})
        else:
            if message.content.strip():
                result.append({'role': message.role, 'content': message.content})
            result.extend({'type': 'function_call', 'call_id': call.id, 'name': call.name, 'arguments': call.arguments} for call in message.tool_calls)
    return result


class StructuredModel:
    """Authenticated Responses/Messages adapter; callers own client disposal.

    Tool state is request-local. A valid protocol terminal and complete identities
    are required before tool chunks leave the adapter. All failures have stable codes.
    """
    def __init__(self, *, model, api_key, base_url, protocol, http_client, options=None):
        self.model, self._key, self.url, self.protocol = model, api_key, base_url.rstrip('/'), protocol
        self.client, self.options = http_client, options or {}

    async def stream(self, request):
        """Yield bounded text, validated calls, cumulative usage and one normalized done."""
        anthropic = self.protocol == 'anthropic_messages'
        streaming = self.options.get('stream', True)
        state = ProtocolState(anthropic)
        started = False
        limit, received = request.max_output_tokens * 12 + 128000, 0
        try:
            if anthropic:
                system, messages = anthropic_messages(request.messages)
                payload = {'model': self.model, 'system': system, 'messages': messages,
                           'max_tokens': request.max_output_tokens, 'stream': streaming}
                if request.tools:
                    payload['tools'] = [{'name': t.name, 'description': t.description, 'input_schema': t.parameters} for t in request.tools]
                headers = {'x-api-key': self._key, 'anthropic-version': '2023-06-01'}
                path = '/messages'
            else:
                payload = {'model': self.model, 'input': responses_messages(request.messages),
                           'max_output_tokens': request.max_output_tokens, 'stream': streaming}
                if request.tools:
                    payload['tools'] = [{'type': 'function', 'name': t.name, 'description': t.description, 'parameters': t.parameters} for t in request.tools]
                headers = {'Authorization': 'Bearer ' + self._key}
                path = '/responses'
            if self.options.get('temperature') is not None:
                payload['temperature'] = self.options['temperature']
            if not anthropic and self.options.get('reasoning_effort'):
                payload['reasoning'] = {'effort': self.options['reasoning_effort']}
            async with self.client.stream('POST', self.url + path, headers=headers, json=payload) as response:
                if not 200 <= response.status_code < 300:
                    body = bytearray()
                    async for part in response.aiter_bytes():
                        if len(body) + len(part) > ERROR_BODY_LIMIT:
                            break
                        body.extend(part)
                    try:
                        error = json.loads(body)
                    except (ValueError, RecursionError):
                        error = None
                    raise failure(error, status=response.status_code, headers=response.headers)
                if not streaming:
                    body = bytearray()
                    async for part in response.aiter_bytes():
                        if len(body) + len(part) > limit:
                            raise RuntimeFault('budget_exhausted')
                        body.extend(part)
                    visible = state.decode_json(json.loads(body))
                    reason, calls = state.complete()
                    usage = usage_chunk(state.usage, self.protocol) if state.usage else None
                    for part in visible:
                        if part:
                            started = True
                            yield ModelChunk('text', text=part)
                else:
                    async for line in response.aiter_lines():
                        received += len(line)
                        if received > limit:
                            raise RuntimeFault('budget_exhausted')
                        if not line.startswith('data:'):
                            continue
                        value = line[5:].strip()
                        if value == '[DONE]':
                            break
                        for part in state.consume(json.loads(value)):
                            if part:
                                started = True
                                yield ModelChunk('text', text=part)
                        if state.terminal:
                            break
                    reason, calls = state.complete()
                    usage = usage_chunk(state.usage, self.protocol) if state.usage else None
                for call in calls:
                    started = True
                    yield ModelChunk('tool_call', tool_call=call)
                if usage:
                    yield usage
                yield ModelChunk('done', finish_reason=reason)
        except RuntimeFault as exc:
            raise mark_output(exc, started) from None
        except httpx.TimeoutException:
            raise ModelFault('model_timeout', output_started=started) from None
        except httpx.TransportError:
            raise ModelFault('model_provider_unavailable', output_started=started) from None
        except Exception:
            raise ModelFault('model_stream_invalid', output_started=started) from None

    async def close(self):
        """Release the injected HTTP client's connection pool."""
        await self.client.aclose()
