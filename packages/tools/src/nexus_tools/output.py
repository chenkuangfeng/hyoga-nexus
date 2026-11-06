"""Model-facing tool output shaping (openspec 2026-11-06-tool-call-hardening, B5).

Conclusions of command output and error traces usually sit at the end, so a cut keeps both ends
(WeKnora `TruncateToolOutput`, internal/agent/tools/truncate.go): 70% head, 30% tail, with a marker
stating the original length. Counts are characters, not bytes, so CJK text is never split mid-character.
"""
from __future__ import annotations

HEAD_SHARE = 0.7
#: Room reserved for the marker so the result never exceeds `limit`.
MARKER_RESERVE = 200


def truncate(text: str, limit: int) -> str:
    """`text` unchanged when it fits; otherwise head + marker + tail, at most `limit` characters."""
    if limit <= 0 or len(text) <= limit:
        return text if limit > 0 else ''
    if limit <= MARKER_RESERVE * 2:
        # Too small for head, marker and tail (short previews): keep the head only.
        return text[:limit]
    # The marker's length depends on the numbers in it: start from a conservative split, then hand the
    # characters the marker did not need to the head until the result fills the limit exactly.
    probe = f'\n[输出已截断：原 {len(text)} 字符，保留前 {limit} + 后 {limit}]\n'
    budget = max(0, limit - len(probe))
    head = int(budget * HEAD_SHARE)
    tail = budget - head
    for _ in range(4):
        marker = f'\n[输出已截断：原 {len(text)} 字符，保留前 {head} + 后 {tail}]\n'
        slack = limit - (head + len(marker) + tail)
        if slack <= 0:
            break
        head += slack
    marker = f'\n[输出已截断：原 {len(text)} 字符，保留前 {head} + 后 {tail}]\n'
    result = text[:head] + marker + (text[-tail:] if tail else '')
    return result[:limit]
