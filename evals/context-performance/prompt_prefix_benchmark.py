"""Compare reusable message-prefix bytes over the existing twenty fixed session cases.

This deterministic structural check does not call a model or predict provider cached_tokens,
latency, answer quality or cache retention. Run from the repository root with:
    uv run python evals/context-performance/prompt_prefix_benchmark.py
"""
from __future__ import annotations

import json
from pathlib import Path

from cases import CASES
from nexus_core.runtime import ModelMessage, ToolCall
from nexus_core.runtime.context import ContextBlock
from nexus_core.runtime.context_assembly import RequestContextAssembler
from nexus_runtimes.native.context.assembly import append_context


def message_bytes(messages) -> bytes:
    """Serialize content and protocol identities, excluding local source IDs and telemetry."""
    return json.dumps([{'role': m.role, 'content': m.content,
                        'tool_calls': [(c.id, c.name, c.arguments) for c in m.tool_calls],
                        'tool_call_id': m.tool_call_id} for m in messages],
                      ensure_ascii=False, separators=(',', ':')).encode()


def prefix_bytes(first: bytes, second: bytes) -> int:
    """Return the exact shared byte prefix, without converting bytes to token claims."""
    return next((i for i, (a, b) in enumerate(zip(first, second)) if a != b), min(len(first), len(second)))


def main() -> None:
    assembler = RequestContextAssembler()
    results = []
    for case in CASES:
        history = [ModelMessage('user', f'Question for {case.name}')]
        for turn_no, turn in enumerate(case.turns):
            for round_no, calls in enumerate(turn.rounds):
                tool_calls = tuple(ToolCall(f'{turn_no}-{round_no}-{i}', name, json.dumps(args, sort_keys=True))
                                   for i, (name, args) in enumerate(calls))
                history.append(ModelMessage('assistant', '', tool_calls))
                history.extend(ModelMessage('tool', 'x' * args['size'], tool_call_id=call.id)
                               for call, (_, args) in zip(tool_calls, calls))
            history.append(ModelMessage('assistant', turn.answer))
        history.append(ModelMessage('user', 'Continue the task using the verified facts.'))
        static = ContextBlock('agent', 'agent', 'system', 'system_static', 0, 'Follow authorized instructions.\n' * 8)
        checkpoint = 'Previously verified task state.'
        legacy_blocks = (static, ContextBlock('checkpoint', 'checkpoint', 'system', 'system_catalog', 40, checkpoint))
        tail_blocks = (static, ContextBlock('checkpoint', 'checkpoint', 'user', 'turn_tail', 40, checkpoint))
        legacy = assembler.assemble(legacy_blocks, tuple(history)).messages
        optimized = assembler.assemble(tail_blocks, tuple(history)).messages
        first_anchor, second_anchor = 'Working reference: turn 1', 'Working reference: turn 2'
        more = [ModelMessage('assistant', 'New verified answer'), ModelMessage('user', 'What next?')]
        old_prefix = prefix_bytes(message_bytes(append_context(legacy, first_anchor)),
                                  message_bytes(append_context([*legacy, *more], second_anchor)))
        new_history = assembler.assemble(tail_blocks, tuple([*history, *more])).messages
        new_prefix = prefix_bytes(message_bytes(append_context(optimized, first_anchor, tail=True)),
                                  message_bytes(append_context(new_history, second_anchor, tail=True)))
        assert new_prefix > old_prefix
        assert message_bytes(history) == message_bytes(list(optimized)[1:-1])
        results.append({'case': case.name, 'legacy_shared_prefix_bytes': old_prefix,
                        'tail_shared_prefix_bytes': new_prefix, 'source_messages_preserved': True})
    report = {'kind': 'offline_structural_prefix_bytes', 'cases': len(results),
              'provider_cached_tokens': None, 'provider_latency_ms': None, 'semantic_quality_evaluated': False,
              'cases_improved': sum(r['tail_shared_prefix_bytes'] > r['legacy_shared_prefix_bytes'] for r in results),
              'results': results}
    target = Path(__file__).with_name('prompt-prefix-results.json')
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({k: v for k, v in report.items() if k != 'results'}, ensure_ascii=False))


if __name__ == '__main__':
    main()
