"""Fuse keyword and vector candidates into one ranking with scores in [0, 1].

Port of WeKnora ``knowledgebase_search_fusion.go`` (``e1f9a6166``):

- vector only: cosine scores kept as they are;
- keyword only: each list divided by its own best score (BM25-like scores are unbounded and not comparable
  across engines);
- both: weighted Reciprocal Rank Fusion ``w_v/(k+rank_v) + w_k/(k+rank_k)`` divided by its maximum
  ``(w_v+w_k)/(k+1)``, so a chunk ranked first by both channels scores 1.

A chunk's rank in a channel is its best position in any one list of that channel, each list ranked by its
own scores (positions in a concatenation of lists would be arbitrary). Each result keeps the per-channel
ranks for diagnosis.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Sequence

RRF_K = 60


@dataclass(frozen=True, slots=True)
class Candidate:
    chunk_id: str
    score: float


@dataclass(slots=True)
class Fused:
    chunk_id: str
    score: float
    ranks: dict[str, int] = field(default_factory=dict)


def _dedupe(candidates: Sequence[Candidate]) -> list[Candidate]:
    best: dict[str, Candidate] = {}
    for item in candidates:
        if not math.isfinite(item.score):
            continue
        current = best.get(item.chunk_id)
        if current is None or item.score > current.score:
            best[item.chunk_id] = item
    return sorted(best.values(), key=lambda item: (-item.score, item.chunk_id))


def _best_ranks(lists: Sequence[Sequence[Candidate]]) -> dict[str, int]:
    ranks: dict[str, int] = {}
    for items in lists:
        for position, item in enumerate(_dedupe(items), start=1):
            if position < ranks.get(item.chunk_id, position + 1):
                ranks[item.chunk_id] = position
    return ranks


def _rescale(items: list[Candidate]) -> list[Candidate]:
    top = max((item.score for item in items), default=0.0)
    if top <= 1:
        return items
    return [Candidate(item.chunk_id, max(item.score, 0.0) / top) for item in items]


def fuse(vector_lists: Sequence[Sequence[Candidate]], keyword_lists: Sequence[Sequence[Candidate]], *,
         vector_weight: float = 1.0, keyword_weight: float = 1.0, k: int = RRF_K) -> list[Fused]:
    """Fused ranking, best first; ties break on chunk id so results are deterministic."""
    vector_lists = [items for items in vector_lists if items]
    keyword_lists = [items for items in keyword_lists if items]
    vector_ranks = _best_ranks(vector_lists)
    keyword_ranks = _best_ranks(keyword_lists)

    def ranks_of(chunk_id: str) -> dict[str, int]:
        out = {}
        if chunk_id in vector_ranks:
            out['vector'] = vector_ranks[chunk_id]
        if chunk_id in keyword_ranks:
            out['keyword'] = keyword_ranks[chunk_id]
        return out

    if not keyword_lists:
        merged = _dedupe([item for items in vector_lists for item in items])
        return [Fused(item.chunk_id, item.score, ranks_of(item.chunk_id)) for item in merged]
    if not vector_lists:
        scaled = [item for items in keyword_lists for item in _rescale(_dedupe(items))]
        return [Fused(item.chunk_id, item.score, ranks_of(item.chunk_id)) for item in _dedupe(scaled)]

    top = (vector_weight + keyword_weight) / (k + 1)
    out = []
    for chunk_id in set(vector_ranks) | set(keyword_ranks):
        score = 0.0
        if chunk_id in vector_ranks:
            score += vector_weight / (k + vector_ranks[chunk_id])
        if chunk_id in keyword_ranks:
            score += keyword_weight / (k + keyword_ranks[chunk_id])
        out.append(Fused(chunk_id, score / top if top > 0 else 0.0, ranks_of(chunk_id)))
    out.sort(key=lambda item: (-item.score, item.chunk_id))
    return out
