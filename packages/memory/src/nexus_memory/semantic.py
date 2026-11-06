"""Pure helpers for semantic memory recall (openspec 2026-11-06-memory-evolution stage 5, D2).

Vectors are compared in process against the owner's own published versions (decision 5): a personal
store holds at most a few hundred entries, so a linear scan is cheaper than running a vector service.
Keyword and vector rankings are fused by reciprocal rank (WeKnora `fuseRankings`), which needs no
calibration between a BM25-like score and a cosine.
"""
from __future__ import annotations

import math
from typing import Iterable, Sequence
from uuid import UUID

#: Lowest cosine kept from the vector channel, and how many candidates each channel contributes.
MIN_COSINE = 0.5
CHANNEL_LIMIT = 25
#: Reciprocal-rank constant (the usual 60: early ranks matter, later ones flatten out).
RRF_K = 60


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    """Cosine similarity; 0 for empty, zero-length or mismatched vectors."""
    if not a or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


def nearest(query: Sequence[float], vectors: Iterable[tuple[UUID, Sequence[float]]], *,
            limit: int = CHANNEL_LIMIT, min_cosine: float = MIN_COSINE) -> list[UUID]:
    """Entry ids by descending cosine to `query`, keeping those at or above `min_cosine`."""
    scored = [(cosine(query, vector), entry_id) for entry_id, vector in vectors]
    scored = [row for row in scored if row[0] >= min_cosine]
    scored.sort(key=lambda row: (-row[0], str(row[1])))
    return [entry_id for _, entry_id in scored[:limit]]


def fuse(*rankings: Sequence[UUID], k: int = RRF_K) -> list[UUID]:
    """Reciprocal-rank fusion of several rankings; ties keep first-seen order."""
    scores: dict[UUID, float] = {}
    order: dict[UUID, int] = {}
    for ranking in rankings:
        for rank, entry_id in enumerate(ranking):
            scores[entry_id] = scores.get(entry_id, 0.0) + 1.0 / (k + rank + 1)
            order.setdefault(entry_id, len(order))
    return sorted(scores, key=lambda entry_id: (-scores[entry_id], order[entry_id]))


def embeddable_text(topic: str, content: str) -> str:
    """Text embedded for an entry: "topic: content", or the content alone (WeKnora `embeddableText`)."""
    topic = (topic or '').strip()
    return f'{topic}：{content}' if topic and topic not in content else content
