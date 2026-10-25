"""Responses/Anthropic wire adapters translated from GA llmcore.py (a9a36b4, MIT).

The adapters share HTTP bounds, but preserve each protocol's message blocks, event ordering,
usage, tool argument deltas and terminal status. Only normalized core chunks leave this file.
"""
import json
from nexus_core.runtime import ModelChunk, RuntimeFault, ToolCall


def usage_chunk(value):
    """Normalize detailed input/output/cache usage without retaining supplier metadata."""
    inp = int(value.get('input_tokens', 0) or 0)
    out = int(value.get('output_tokens', 0) or 0)
    cached = int(value.get('cache_read_input_tokens', 0) or (value.get('input_tokens_details') or {}).get('cached_tokens', 0) or 0)
    creation = int(value.get('cache_creation_input_tokens', 0) or 0)
    return ModelChunk('usage', total_tokens=int(value.get('total_tokens') or inp + out + cached + creation),
                      usage={'input': inp, 'output': out, 'cache_read': cached, 'cache_creation': creation})


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
    """One protocol client with authenticated transport supplied by the application root."""
    def __init__(self, *, model, api_key, base_url, protocol, http_client, options=None):
        self.model, self._key, self.url, self.protocol = model, api_key, base_url.rstrip('/'), protocol
        self.client, self.options = http_client, options or {}

    async def stream(self, request):
        """Yield bounded text/tools/usage and exactly one terminal chunk, or a stable failure."""
        anthropic = self.protocol == 'anthropic_messages'
        streaming = self.options.get('stream', True)
        if anthropic:
            system, messages = anthropic_messages(request.messages)
            payload = {'model': self.model, 'system': system, 'messages': messages, 'max_tokens': request.max_output_tokens,
                       'stream': streaming}
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
        calls, reason, usage = {}, '', {}
        limit, received = request.max_output_tokens * 12 + 128000, 0
        try:
            async with self.client.stream('POST', self.url + path, headers=headers, json=payload) as response:
                if response.status_code >= 400:
                    raise RuntimeFault('model_rate_limited' if response.status_code == 429 else 'model_provider_unavailable')
                if not streaming:
                    body = bytearray()
                    async for part in response.aiter_bytes():
                        body.extend(part)
                        if len(body) > limit:
                            raise RuntimeFault('budget_exhausted')
                    data = json.loads(body)
                    if anthropic:
                        for block in data.get('content', []):
                            if block['type'] == 'text':
                                yield ModelChunk('text', text=block['text'])
                            elif block['type'] == 'tool_use':
                                calls[block['id']] = {'id': block['id'], 'name': block['name'], 'arguments': json.dumps(block.get('input', {}))}
                        usage = data.get('usage', {}); reason = data.get('stop_reason', '')
                    else:
                        for item in data.get('output', []):
                            if item['type'] == 'message':
                                for block in item.get('content', []):
                                    if block['type'] == 'output_text':
                                        yield ModelChunk('text', text=block['text'])
                            elif item['type'] == 'function_call':
                                calls[item['id']] = {'id': item['call_id'], 'name': item['name'], 'arguments': item['arguments']}
                        usage = data.get('usage', {}); reason = 'max_tokens' if data.get('status') == 'incomplete' else 'stop'
                else:
                    async for line in response.aiter_lines():
                        received += len(line)
                        if received > limit:
                            raise RuntimeFault('budget_exhausted')
                        if not line.startswith('data:') or line[5:].strip() == '[DONE]':
                            continue
                        data = json.loads(line[5:].strip()); kind = data.get('type', '')
                        if kind in ('error', 'response.failed'):
                            raise RuntimeFault('model_provider_unavailable')
                        if anthropic:
                            if kind == 'message_start':
                                usage.update(data.get('message', {}).get('usage', {}))
                            elif kind == 'content_block_start' and data.get('content_block', {}).get('type') == 'tool_use':
                                block = data['content_block']; calls[data['index']] = {'id': block['id'], 'name': block['name'], 'arguments': ''}
                            elif kind == 'content_block_delta':
                                delta = data['delta']
                                if delta['type'] == 'text_delta':
                                    yield ModelChunk('text', text=delta['text'])
                                elif delta['type'] == 'input_json_delta':
                                    calls[data['index']]['arguments'] += delta['partial_json']
                            elif kind == 'message_delta':
                                reason = data.get('delta', {}).get('stop_reason', reason)
                                usage.update(data.get('usage', {}))
                            elif kind == 'message_stop' and not reason:
                                raise RuntimeFault('model_stream_invalid')
                        else:
                            if kind == 'response.output_text.delta':
                                yield ModelChunk('text', text=data['delta'])
                            elif kind == 'response.output_item.added' and data.get('item', {}).get('type') == 'function_call':
                                item = data['item']; calls[item['id']] = {'id': item['call_id'], 'name': item['name'], 'arguments': item.get('arguments', '')}
                            elif kind == 'response.function_call_arguments.delta':
                                calls[data['item_id']]['arguments'] += data['delta']
                            elif kind == 'response.function_call_arguments.done':
                                calls[data['item_id']]['arguments'] = data['arguments']
                            elif kind in ('response.completed', 'response.incomplete'):
                                usage = data.get('response', {}).get('usage', {})
                                reason = 'max_tokens' if kind == 'response.incomplete' else 'stop'
                if not reason:
                    raise RuntimeFault('model_stream_invalid')
                capped = reason in ('length', 'max_tokens')
                for call in calls.values():
                    if not call['arguments']:
                        call['arguments'] = '{}'
                    yield ModelChunk('tool_call', tool_call=ToolCall(**call))
                if usage:
                    yield usage_chunk(usage)
                normalized = 'length' if capped else 'tool_calls' if calls else 'stop' if reason in ('end_turn', 'stop', 'stop_sequence', 'tool_use') else reason
                yield ModelChunk('done', finish_reason=normalized)
        except RuntimeFault:
            raise
        except Exception as exc:
            import httpx
            raise RuntimeFault('model_timeout' if isinstance(exc, httpx.TimeoutException) else 'model_stream_invalid') from None

    async def close(self):
        await self.client.aclose()
