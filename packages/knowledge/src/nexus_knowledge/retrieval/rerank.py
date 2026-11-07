"""Rerank policy (port of WeKnora ``internal/reranking``: ``rerank.go``, ``mmr.go``; openspec K5.3b).

A rerank model scores each (query, passage) pair. This module decides what to do with the scores:

- passages are trimmed to the model's character limit;
- a score threshold keeps relevant passages; when none passes and the threshold is above :data:`DEGRADE_FLOOR`
  it is relaxed once (x :data:`DEGRADE_FACTOR`); when still none passes the single best passage is kept if its
  score is at least :data:`FALLBACK_MIN_SCORE`, otherwise nothing is returned (all below threshold);
- the final score blends the model score with the retrieval score: ``0.6 * model + 0.3 * base + 0.1``;
- the top ``k`` are chosen with MMR (lambda 0.7) so near-duplicate passages do not crowd out others.

Model failures never fail a search: the retrieval order is kept and the outcome says why. Pure functions; the
model call and credentials live in the platform.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Sequence

from ..text import tokenize

DEFAULT_THRESHOLD = 0.2
FALLBACK_MIN_SCORE = 0.15
DEGRADE_FLOOR = 0.3
DEGRADE_FACTOR = 0.7
MMR_LAMBDA = 0.7
MAX_CANDIDATES = 50

OUTCOMES = ('ok', 'threshold_degraded', 'fallback_top1', 'all_below_threshold', 'no_candidates', 'no_model',
            'model_unavailable', 'model_error', 'disabled')


@dataclass
class Diagnostics:
    outcome: str = 'disabled'
    model_id: str = ''
    threshold: float = DEFAULT_THRESHOLD
    effective_threshold: float = DEFAULT_THRESHOLD
    candidate_count: int = 0
    result_count: int = 0
    top_score: float | None = None
    error: str = ''


@dataclass(frozen=True)
class Scored:
    """A candidate that passed: its index in the input list, model score and blended score."""

    index: int
    model_score: float
    score: float


def fit_passage(text: str, limit: int) -> str:
    return text[:limit] if limit > 0 and len(text) > limit else text


def blend(model_score: float, base_score: float) -> float:
    return min(max(0.6 * model_score + 0.3 * base_score + 0.1, 0.0), 1.0)


def apply_threshold(scores: Sequence[tuple[int, float]], threshold: float,
                    fallback_min: float = FALLBACK_MIN_SCORE) -> tuple[list[tuple[int, float]], str, float]:
    """``(passing, outcome, effective threshold)`` for ``(index, model score)`` pairs."""
    passing = [item for item in scores if item[1] >= threshold]
    if passing:
        return passing, 'ok', threshold
    if threshold > DEGRADE_FLOOR:
        threshold = max(threshold * DEGRADE_FACTOR, DEGRADE_FLOOR)
        passing = [item for item in scores if item[1] >= threshold]
        if passing:
            return passing, 'threshold_degraded', threshold
    if scores:
        top = max(scores, key=lambda item: item[1])
        if top[1] >= fallback_min:
            return [top], 'fallback_top1', threshold
    return [], 'all_below_threshold', threshold


def select_mmr(texts: Sequence[str], scores: Sequence[float], k: int, lam: float = MMR_LAMBDA) -> list[int]:
    """Indices chosen by maximal marginal relevance: relevance minus similarity to what is already selected."""
    count = len(texts)
    if k <= 0 or count == 0:
        return []
    tokens = [set(tokenize(t).split()) for t in texts]
    remaining = list(range(count))
    redundancy = [0.0] * count
    selected: list[int] = []
    while len(selected) < min(k, count):
        best = max(remaining, key=lambda i: (lam * scores[i] - (1 - lam) * redundancy[i], -i))
        selected.append(best)
        remaining.remove(best)
        for i in remaining:
            union = len(tokens[i] | tokens[best])
            if union:
                redundancy[i] = max(redundancy[i], len(tokens[i] & tokens[best]) / union)
    return selected


def rerank(model_scores: Sequence[tuple[int, float]], base_scores: Sequence[float], texts: Sequence[str], *,
           threshold: float, top_k: int, diag: Diagnostics) -> list[Scored]:
    """Final ordering from model scores. Fills ``diag`` and returns the chosen candidates, best first."""
    valid = [(i, s) for i, s in model_scores if 0 <= i < len(base_scores) and math.isfinite(s)]
    diag.top_score = max((s for _, s in valid), default=None)
    passing, diag.outcome, diag.effective_threshold = apply_threshold(valid, threshold)
    scored = sorted((Scored(i, s, blend(s, base_scores[i])) for i, s in passing),
                    key=lambda item: (-item.score, -item.model_score, item.index))
    picks = select_mmr([texts[s.index] for s in scored], [s.score for s in scored], top_k) if top_k > 0 else \
        list(range(len(scored)))
    result = [scored[p] for p in picks]
    diag.result_count = len(result)
    return result
