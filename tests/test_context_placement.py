"""Placement of the working-memory envelope (P1) and declared read-only tools (P9)."""
import pytest

from nexus_core.native import NativePolicy
from nexus_core.runtime import ModelMessage, ToolCall, ToolDefinition
from nexus_runtimes.native.context.assembly import append_context


def _exchange():
    return [
        ModelMessage('system', 'SYSTEM'),
        ModelMessage('user', 'question'),
        ModelMessage('assistant', '', (ToolCall('call_1', 'read', '{}'),)),
        ModelMessage('tool', 'result', tool_call_id='call_1'),
    ]


def test_default_placement_keeps_envelope_after_system():
    result = append_context(_exchange(), 'ENVELOPE')
    assert [m.content for m in result][:2] == ['SYSTEM', 'ENVELOPE']


def test_tail_placement_keeps_the_prefix_byte_stable_across_turns():
    first = append_context(_exchange(), 'ENVELOPE-TURN-1', tail=True)
    second = append_context(_exchange() + [ModelMessage('user', 'next')], 'ENVELOPE-TURN-2', tail=True)
    # Everything before the envelope is identical, so the provider's cached prefix is reusable.
    assert first[:-1] == _exchange()
    assert second[:-1] == _exchange() + [ModelMessage("user", "next")]


def test_tail_placement_never_splits_a_tool_exchange():
    result = append_context(_exchange(), 'ENVELOPE', tail=True)
    call_index = next(i for i, m in enumerate(result) if m.tool_calls)
    assert result[call_index + 1].role == 'tool'  # results still immediately follow the call


def test_empty_context_is_a_no_op():
    assert append_context(_exchange(), '', tail=True) == _exchange()


def test_read_only_tool_with_side_effects_is_rejected():
    with pytest.raises(ValueError):
        ToolDefinition('write', 'd', {}, read_only=True, side_effects=True)
    with pytest.raises(ValueError):
        ToolDefinition('approve', 'd', {}, read_only=True, requires_approval=True)


def test_declared_read_only_tool_is_accepted():
    tool = ToolDefinition('read', 'd', {}, read_only=True, idempotent=True)
    assert tool.read_only and tool.idempotent


def test_parallel_reads_and_tail_placement_are_on_by_default():
    policy = NativePolicy()
    assert policy.parallel_reads is True
    assert policy.working_memory_tail is True
