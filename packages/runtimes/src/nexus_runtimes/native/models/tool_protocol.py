"""Opt-in GA text tool protocol, derived from llmcore._parse_text_tool_calls (MIT).

Parsing never executes code; calls still pass schema validation and the authorization gateway.
Native calls take precedence so identical embedded text cannot execute a second operation.
"""
import json
import re
from dataclasses import replace
from contextlib import aclosing
from .errors import mark_output
from nexus_core.schema import sanitize as sanitize_schema
from nexus_core.runtime import ModelChunk, ModelMessage, RuntimeFault, ToolCall


def parse_text_calls(content: str):
    """Parse GA XML/JSON-array forms; reject malformed or ambiguous structures explicitly."""
    calls = []
    pattern = r'<(?:tool_use|tool_call)>((?:(?!<(?:tool_use|tool_call)>).){1,}?)</(?:tool_use|tool_call)>'
    matches = list(re.finditer(pattern, content, flags=re.S))
    raw_calls = []
    if matches:
        for match in matches:
            try:
                raw_calls.append(json.loads(match.group(1).strip()))
            except (ValueError, RecursionError):
                raise RuntimeFault('model_tool_protocol_invalid') from None
        visible = re.sub(pattern, '', content, flags=re.S).strip()
    else:
        array = re.search(r'\[\s*\{\s*"type"\s*:\s*"tool_use"', content)
        if array:
            try:
                raw_calls = json.loads(content[array.start():])
            except (ValueError, RecursionError):
                raise RuntimeFault('model_tool_protocol_invalid') from None
            visible = content[:array.start()].strip()
        elif '<tool_use>' in content or '<tool_call>' in content:
            raise RuntimeFault('model_tool_protocol_invalid')
        else:
            return [], content
    for index, item in enumerate(raw_calls):
        if not isinstance(item, dict) or not isinstance(item.get('name'), str):
            raise RuntimeFault('model_tool_protocol_invalid')
        arguments = item.get('arguments', item.get('args', item.get('input', {})))
        if not isinstance(arguments, dict):
            raise RuntimeFault('model_tool_protocol_invalid')
        calls.append(ToolCall(item.get('id') or f'text-call-{index}', item['name'], json.dumps(arguments, ensure_ascii=False)))
    return calls, visible


class TextToolModel:
    """Wrap a text-only supplier with GA protocol prompts and validated tool-call extraction."""
    def __init__(self, model):
        self.model = model
        self._sequence = 0

    async def stream(self, request):
        schema = json.dumps([{'name': t.name, 'description': t.description, 'parameters': sanitize_schema(t.parameters)} for t in request.tools], ensure_ascii=False)
        guidance = ModelMessage('system', 'When an authorized tool is needed, emit <tool_use>{"name":"tool_name","arguments":{}}</tool_use>. '
            'After tool results, continue until the user task is complete. Mounted tools: ' + schema)
        actual = replace(request, messages=(guidance, *request.messages), tools=())
        text, native, usage, reason = '', [], [], ''
        started = False
        try:
            async with aclosing(self.model.stream(actual)) as stream:
                async for chunk in stream:
                    if reason and chunk.kind != 'usage':
                        raise RuntimeFault('model_stream_invalid')
                    started |= chunk.kind in ('text', 'tool_call', 'done')
                    if chunk.kind == 'text':
                        text += chunk.text
                    elif chunk.kind == 'tool_call':
                        native.append(chunk)
                    elif chunk.kind == 'usage':
                        usage[:] = [chunk]
                    elif chunk.kind == 'done':
                        if reason:
                            raise RuntimeFault('model_stream_invalid')
                        reason = chunk.finish_reason
                    if len(text) > request.max_output_tokens * 8 or len(native) > 32:
                        raise RuntimeFault('budget_exhausted')
            if reason not in ('stop', 'tool_calls', 'length', 'max_tokens', 'content_filter'):
                raise RuntimeFault('model_stream_invalid')
        except RuntimeFault as exc:
            # The supplier may have streamed data even though this parser buffers it.
            # Preserve public non-tool text on failure, but never expose partial calls.
            if text and '<tool_' not in text:
                yield ModelChunk('text', text=text)
            raise mark_output(exc, started) from None
        self._sequence += 1
        calls, visible = ([], text) if native or reason in ('length', 'max_tokens', 'content_filter') else parse_text_calls(text)
        if visible:
            yield ModelChunk('text', text=visible)
        for chunk in native if reason not in ('content_filter', 'length', 'max_tokens') else ():
            yield chunk
        for call in calls:
            yield ModelChunk('tool_call', tool_call=replace(call, id=f'text-{self._sequence}-{call.id}'))
        for chunk in usage:
            yield chunk
        yield ModelChunk('done', finish_reason=reason if reason in ('length', 'max_tokens', 'content_filter') else 'tool_calls' if native or calls else reason)

    async def close(self):
        await self.model.close()
