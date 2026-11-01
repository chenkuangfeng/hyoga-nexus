"""Fixed session set for the context-performance baseline (openspec 2026-11-01-context-token-performance, section 一).

Twenty sessions cover single and multi-call turns, outputs from short to very long, multi-turn
conversations, and follow-up questions that depend on an earlier tool result. The set is fixed:
changing a case invalidates earlier baseline numbers, so add new cases instead of editing these.

A turn is scripted: `rounds` are the tool calls the model makes in order (each round is one model
call), then `answer` is the final text. Tool `fetch(size)` returns `size` characters ending in a
marker, so the harness can see whether the marker reached the model.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Turn:
    rounds: tuple = ()
    answer: str = 'ok'


@dataclass(frozen=True)
class Case:
    name: str
    turns: tuple
    reader: bool = True  # bind read_tool_output (the P2 configuration); False measures the old 4000-char cap


def _call(size):
    return ('fetch', {'size': size})


CASES = (
    # A. One tool call, output length from short to very long.
    Case('single-100', (Turn(((_call(100),),), 'answer 100'),)),
    Case('single-900', (Turn(((_call(900),),), 'answer 900'),)),
    Case('single-2500', (Turn(((_call(2500),),), 'answer 2500'),)),
    Case('single-8000', (Turn(((_call(8000),),), 'answer 8000'),)),
    Case('single-30000', (Turn(((_call(30000),),), 'answer 30000'),)),
    # B. Several model rounds within one turn.
    Case('multi-1500x2', (Turn(((_call(1500),), (_call(1500),)), 'answer pair'),)),
    Case('multi-6000-300x2', (Turn(((_call(6000), _call(300)), (_call(300),)), 'answer mixed'),)),
    Case('multi-rounds-4', (Turn(((_call(800),), (_call(2200),), (_call(400),), (_call(9000),)), 'answer four'),)),
    # C. Multi-turn conversations without tools.
    Case('chat-3turns', (Turn((), 'first'), Turn((), 'second'), Turn((), 'third'))),
    Case('chat-6turns', tuple(Turn((), f'reply {index}') for index in range(6))),
    Case('chat-long-answers', tuple(Turn((), 'long answer ' * 200) for _ in range(3))),
    # D. Multi-turn with a tool call in every turn.
    Case('tools-3turns', (Turn(((_call(2000),),), 'a1'), Turn(((_call(5000),),), 'a2'), Turn(((_call(800),),), 'a3'))),
    Case('tools-5turns-mixed', (Turn(((_call(300),),), 'a1'), Turn(((_call(12000),),), 'a2'),
                                Turn((), 'a3'), Turn(((_call(2600),), (_call(40),)), 'a4'), Turn((), 'a5'))),
    Case('tools-heavy-turns', tuple(Turn(((_call(7000),),), f'h{index}') for index in range(4))),
    # E. Follow-up questions that depend on an earlier tool result (the quality-sensitive samples).
    Case('followup-1500', (Turn(((_call(1500),),), 'value from doc is 1500'), Turn((), 'the value was 1500'))),
    Case('followup-3000', (Turn(((_call(3000),),), 'value from doc is 3000'), Turn((), 'the value was 3000'))),
    Case('followup-9000', (Turn(((_call(9000),),), 'value from doc is 9000'), Turn((), 'the value was 9000'))),
    Case('followup-20000', (Turn(((_call(20000),),), 'value from doc is 20000'), Turn((), 'the value was 20000'))),
    Case('followup-no-reader-9000', (Turn(((_call(9000),),), 'value from doc is 9000'), Turn((), 'the value was 9000')),
         reader=False),
    Case('followup-chain', (Turn(((_call(4000),),), 'first doc'), Turn(((_call(6000),),), 'second doc'),
                            Turn((), 'compare both'))),
)

assert len(CASES) == 20, 'the baseline set is fixed at 20 sessions'
assert len({case.name for case in CASES}) == len(CASES)
