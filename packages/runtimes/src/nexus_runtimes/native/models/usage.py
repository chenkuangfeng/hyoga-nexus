"""Protocol-specific cumulative token accounting derived from locked WeKnora usage code.

Counts are nonnegative JSON integers up to 2**53-1 (the exact integer range shared
with browser JSON consumers). Missing/null fields are unknown and normalize to zero.
"""
from nexus_core.runtime import ModelChunk, RuntimeFault

MAX_TOKENS = 2**53 - 1


def count(value):
    """Validate one counter without coercing booleans, strings or fractional values."""
    if value is None:
        return 0
    if type(value) is not int or not 0 <= value <= MAX_TOKENS:
        raise RuntimeFault('model_stream_invalid')
    return value


def usage_chunk(value, protocol='openai_responses'):
    """Normalize one cumulative snapshot, counting cache as a subset only where specified."""
    if not isinstance(value, dict):
        raise RuntimeFault('model_stream_invalid')
    chat = protocol == 'openai_chat_completions'
    anthropic = protocol == 'anthropic_messages'
    inp = count(value.get('prompt_tokens' if chat else 'input_tokens'))
    out = count(value.get('completion_tokens' if chat else 'output_tokens'))
    details = value.get('prompt_tokens_details' if chat else 'input_tokens_details')
    if details is None:
        details = {}
    if not isinstance(details, dict):
        raise RuntimeFault('model_stream_invalid')
    if anthropic:
        cached = count(value.get('cache_read_input_tokens'))
        creation = count(value.get('cache_creation_input_tokens'))
    else:
        # WeKnora priority: DeepSeek hit/miss, relay cache counters, details, Kimi.
        cached = count(next((v for v in (value.get('prompt_cache_hit_tokens'),
            value.get('cache_read_input_tokens'), details.get('cached_tokens'), value.get('cached_tokens')) if v is not None), None))
        creation = count(next((v for v in (value.get('cache_creation_input_tokens'), details.get('cache_write_tokens')) if v is not None), None))
        count(value.get('prompt_cache_miss_tokens'))
        if cached > inp or creation > inp:
            raise RuntimeFault('model_stream_invalid')
    total = count(inp + out + cached + creation) if anthropic else count(inp + out)
    explicit = value.get('total_tokens')
    if explicit is not None:
        total = count(explicit)
    return ModelChunk('usage', total_tokens=total,
                      usage={'input': inp, 'output': out, 'cache_read': cached, 'cache_creation': creation})
