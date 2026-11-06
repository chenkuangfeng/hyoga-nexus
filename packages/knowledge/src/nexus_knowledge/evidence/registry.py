"""Per-Run evidence registry: every passage shown to the model gets a stable ``[ID:n]`` handle.

Port of RAGFlow ``internal/agentic_rag/evidence_registry.go`` and ``citations.go`` (``e5a5060c4``):

- a chunk gets its number the first time it reaches the model and keeps it for the rest of the Run;
- the same text served again is reported as a repeat, so the tool prints only the handle instead of
  re-sending tokens the model already holds (keyed by chunk id + text hash: a different window of the same
  chunk is new information);
- at the end of the Run the answer's ``[ID:n]`` handles are resolved against the registry. Unknown handles
  produce no citation; the caller records them as invalid (decision 7: the Run does not fail).

The registry is stored in the Run's progress (``to_state``/``from_state``), so numbers survive suspension
and resume. Numbers start at 1 for readability.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any

_HANDLE = re.compile(r'\[ID:(\d+)\]')


def _text_key(chunk_id: str, text: str) -> str:
    return chunk_id + '\x1f' + hashlib.sha256(text.encode()).hexdigest()[:16]


@dataclass
class EvidenceRegistry:
    order: list[str] = field(default_factory=list)
    refs: dict[str, dict[str, Any]] = field(default_factory=dict)
    served: set[str] = field(default_factory=set)

    def stamp(self, chunk_id: str, ref: dict[str, Any] | None = None) -> int:
        """Handle of a chunk, allocating the next number on first sight. ``ref`` (document, version, page...)
        is kept from the first call and returned in citations."""
        if chunk_id not in self.refs:
            self.order.append(chunk_id)
            self.refs[chunk_id] = dict(ref or {})
        return self.order.index(chunk_id) + 1

    def serve(self, chunk_id: str, text: str, ref: dict[str, Any] | None = None) -> tuple[int, bool]:
        """``(handle, is_new_text)``: False when this exact text of this chunk was already shown in the Run."""
        handle = self.stamp(chunk_id, ref)
        key = _text_key(chunk_id, text)
        new = key not in self.served
        self.served.add(key)
        return handle, new

    def resolve(self, handle: int) -> str | None:
        return self.order[handle - 1] if 1 <= handle <= len(self.order) else None

    def to_state(self) -> dict[str, Any]:
        return {'order': list(self.order), 'refs': {k: dict(v) for k, v in self.refs.items()},
                'served': sorted(self.served)}

    @classmethod
    def from_state(cls, state: dict[str, Any] | None) -> 'EvidenceRegistry':
        if not state:
            return cls()
        order = [str(item) for item in state.get('order', [])]
        refs = {str(k): dict(v) for k, v in (state.get('refs') or {}).items()}
        for chunk_id in order:
            refs.setdefault(chunk_id, {})
        return cls(order, refs, set(state.get('served', [])))


def extract_handles(answer: str) -> list[int]:
    """``[ID:n]`` numbers in first-appearance order, de-duplicated."""
    seen: dict[int, None] = {}
    for match in _HANDLE.finditer(answer or ''):
        seen.setdefault(int(match.group(1)), None)
    return list(seen)


def resolve_citations(answer: str, registry: EvidenceRegistry) -> tuple[list[dict[str, Any]], list[int]]:
    """``(citations, invalid_handles)``. Each citation is ``{'handle': n, 'chunk_id': ..., **ref}``."""
    citations, invalid = [], []
    for handle in extract_handles(answer):
        chunk_id = registry.resolve(handle)
        if chunk_id is None:
            invalid.append(handle)
        else:
            citations.append({'handle': handle, 'chunk_id': chunk_id, **registry.refs.get(chunk_id, {})})
    return citations, invalid
