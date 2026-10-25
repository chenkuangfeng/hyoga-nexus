"""Per-response tool/terminal state translated from locked WeKnora protocol clients.

No execution occurs here. Calls become candidates only after a valid terminal and
complete identities/arguments; filtering and truncation always take precedence.
"""
import json
from nexus_core.runtime import RuntimeFault, ToolCall
from ..errors import failure
from ..usage import count


def invalid():
    raise RuntimeFault('model_stream_invalid')


def object_value(value):
    if not isinstance(value, dict):
        invalid()
    return value


def text(value):
    if not isinstance(value, str):
        invalid()
    return value


def finish(reason, calls):
    """Normalize known reasons; never let a tool hide filtering or truncation."""
    if reason in ('length', 'max_tokens', 'model_context_window_exceeded'):
        return 'length'
    if reason in ('content_filter', 'refusal'):
        return 'content_filter'
    if reason not in ('stop', 'end_turn', 'stop_sequence', 'tool_use', 'tool_calls'):
        invalid()
    if reason in ('tool_use', 'tool_calls') and not calls:
        invalid()
    return 'tool_calls' if calls else 'stop'


def validate_calls(calls, reason):
    """Keep bounded truncated calls for existing recovery, never expose filtered calls."""
    if reason == 'content_filter':
        return []
    if len(calls) > 32:
        invalid()
    result, seen = [], set()
    for call in calls:
        identity, name, arguments = call['id'], call['name'], call['arguments']
        if (not isinstance(identity, str) or not identity or len(identity) > 255 or identity in seen
                or not isinstance(name, str) or not name or len(name) > 64
                or not isinstance(arguments, str) or len(arguments) > 128000):
            invalid()
        if reason != 'length':
            try:
                value = json.loads(arguments)
            except (ValueError, RecursionError):
                invalid()
            if not isinstance(value, dict):
                invalid()
        seen.add(identity)
        result.append(ToolCall(identity, name, arguments))
    return result


class ProtocolState:
    """Own one structured response's fields; counters are cumulative snapshots."""
    def __init__(self, anthropic):
        self.anthropic = anthropic
        self.calls, self.aliases = {}, {}
        self.usage, self.reason = {}, ''
        self.terminal = False
        self.open_blocks = set()

    def index(self, data):
        value = data.get('index', data.get('output_index'))
        if type(value) is not int or value < 0:
            invalid()
        return value

    def response_reason(self, data, event=None):
        object_value(data)
        if data.get('error') is not None or data.get('status') == 'failed':
            raise failure(data)
        status = data.get('status', event)
        if status == 'completed':
            return 'stop'
        if status != 'incomplete':
            invalid()
        reason = object_value(data.get('incomplete_details')).get('reason')
        if reason == 'max_output_tokens':
            return 'length'
        if reason == 'content_filter':
            return 'content_filter'
        invalid()

    def key(self, data, item=None):
        """Resolve item IDs and index fallbacks, rejecting contradictory aliases."""
        identity = (item or {}).get('id') if item is not None else data.get('item_id')
        if identity is not None and (not isinstance(identity, str) or not identity):
            invalid()
        index = data.get('output_index')
        if index is not None:
            if type(index) is not int or index < 0:
                invalid()
            fallback = ('index', index)
        else:
            fallback = None
        primary = ('id', identity) if identity else fallback
        if primary is None:
            invalid()
        if primary in self.aliases:
            canonical = self.aliases[primary]
            if fallback is not None and fallback in self.aliases and self.aliases[fallback] != canonical:
                invalid()
        else:
            canonical = self.aliases.get(fallback, primary)
        self.aliases[primary] = canonical
        if fallback is not None:
            self.aliases[fallback] = canonical
        return canonical

    def add_response_call(self, data, item):
        key = self.key(data, item)
        call = {'id': text(item.get('call_id')), 'name': text(item.get('name')),
                'arguments': text(item.get('arguments', '')), 'delta': False, 'closed': False, 'order': data.get('output_index', len(self.calls))}
        if key in self.calls:
            old = self.calls[key]
            if old['id'] != call['id'] or old['name'] != call['name']:
                invalid()
            return key
        self.calls[key] = call
        return key

    def decode_json(self, data):
        """Validate the whole envelope before exposing any content from a JSON response."""
        object_value(data)
        if data.get('error') is not None or data.get('type') == 'error':
            raise failure(data)
        visible = []
        if self.anthropic:
            self.reason = text(data.get('stop_reason'))
            blocks = data.get('content')
            if not isinstance(blocks, list):
                invalid()
            for i, block in enumerate(blocks):
                object_value(block)
                if block.get('type') == 'text':
                    visible.append(text(block.get('text')))
                elif block.get('type') == 'tool_use':
                    value = block.get('input', {})
                    if not isinstance(value, dict):
                        invalid()
                    self.calls[i] = {'id': block.get('id'), 'name': block.get('name'), 'arguments': json.dumps(value)}
        else:
            self.reason = self.response_reason(data)
            output = data.get('output', [])
            if not isinstance(output, list):
                invalid()
            for i, item in enumerate(output):
                object_value(item)
                if item.get('type') == 'message':
                    for block in item.get('content', []):
                        object_value(block)
                        if block.get('type') in ('output_text', 'text'):
                            visible.append(text(block.get('text')))
                elif item.get('type') == 'function_call':
                    self.add_response_call({'output_index': i}, item)
        self.usage = object_value(data.get('usage') or {})
        self.terminal = True
        return visible

    def consume(self, data):
        """Consume one decoded SSE data line, returning text; unknown event types are harmless."""
        object_value(data)
        if self.terminal:
            invalid()
        kind = data.get('type')
        if kind == 'error':
            raise failure(data)
        if kind == 'response.failed':
            raise failure(data.get('response'))
        if self.anthropic:
            return self._anthropic(data, kind)
        if kind == 'response.output_text.delta':
            return [text(data.get('delta'))]
        if kind in ('response.output_item.added', 'response.output_item.done'):
            item = object_value(data.get('item'))
            if item.get('type') == 'function_call':
                key = self.add_response_call(data, item)
                call = self.calls[key]
                if kind.endswith('.done'):
                    arguments = text(item.get('arguments', ''))
                    if call['delta'] and arguments and arguments != call['arguments']:
                        invalid()
                    if arguments:
                        call['arguments'] = arguments
                    call['closed'] = True
        elif kind in ('response.function_call_arguments.delta', 'response.function_call_arguments.done'):
            key = self.key(data)
            if key not in self.calls:
                invalid()
            call = self.calls[key]
            if call['closed']:
                invalid()
            if kind.endswith('.delta'):
                call['arguments'] += text(data.get('delta')); call['delta'] = True
            else:
                arguments = text(data.get('arguments'))
                if call['delta'] and arguments != call['arguments']:
                    invalid()
                call['arguments'] = arguments
        elif kind in ('response.completed', 'response.incomplete'):
            status = kind.removeprefix('response.')
            response = object_value(data.get('response'))
            if response.get('status', status) != status:
                invalid()
            self.reason = self.response_reason(response, status)
            self.usage = object_value(response.get('usage') or {})
            self.terminal = True
        return []

    def _anthropic(self, data, kind):
        if kind == 'message_start':
            self.usage.update(object_value(object_value(data.get('message')).get('usage') or {}))
        elif kind == 'content_block_start':
            index = self.index(data)
            if index in self.open_blocks or index in self.calls:
                invalid()
            self.open_blocks.add(index)
            block = object_value(data.get('content_block'))
            if block.get('type') == 'tool_use':
                value = block.get('input', {})
                if not isinstance(value, dict):
                    invalid()
                self.calls[index] = {'id': block.get('id'), 'name': block.get('name'),
                    'arguments': json.dumps(value), 'delta': False, 'closed': False}
            elif block.get('type') == 'text':
                return [text(block.get('text', ''))]
        elif kind == 'content_block_delta':
            delta = object_value(data.get('delta'))
            if delta.get('type') == 'text_delta':
                return [text(delta.get('text'))]
            if delta.get('type') == 'input_json_delta':
                index = self.index(data)
                if index not in self.calls or self.calls[index]['closed']:
                    invalid()
                call = self.calls[index]
                if not call['delta']:
                    call['arguments'] = ''; call['delta'] = True
                call['arguments'] += text(delta.get('partial_json'))
        elif kind == 'content_block_stop':
            index = self.index(data)
            if index not in self.open_blocks:
                invalid()
            self.open_blocks.remove(index)
            if index in self.calls:
                self.calls[index]['closed'] = True
        elif kind == 'message_delta':
            reason = object_value(data.get('delta') or {}).get('stop_reason')
            if reason:
                if self.reason and self.reason != reason:
                    invalid()
                self.reason = text(reason)
            update = object_value(data.get('usage') or {})
            for name, value in update.items():
                if name in ('input_tokens', 'cache_read_input_tokens', 'cache_creation_input_tokens'):
                    self.usage[name] = max(count(self.usage.get(name)), count(value))
                else:
                    self.usage[name] = value
        elif kind == 'message_stop':
            self.terminal = True
        return []

    def complete(self):
        """Produce a normalized terminal and bounded candidates, or fail closed."""
        if self.anthropic:
            if any(not c.get('closed', True) for c in self.calls.values()):
                invalid()
        elif not self.terminal:
            invalid()
        calls = [self.calls[k] for k in sorted(self.calls)] if self.anthropic else sorted(self.calls.values(), key=lambda c: c['order'])
        reason = finish(self.reason, calls)
        return reason, validate_calls(calls, reason)
