"""Reranking of search hits with the searcher's own rerank model (openspec 2026-11-06-knowledge-base K5.3b).

A knowledge base opts in with ``settings.rerank_config = {"enabled": true, "model_id": <rerank model version>,
"threshold": 0.2, "top_k": 0}``. The model is a query-time model, so it runs with the *searching* user's key
(decision 6); a user who cannot use it, a missing client or a provider error keeps the retrieval order and the
outcome is reported (WeKnora behaviour: reranking never fails a search). Policy (thresholds, blending, MMR) lives in
:mod:`nexus_knowledge.retrieval.rerank`.

When several bases are searched together the first base with reranking enabled decides the model and threshold.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable
from uuid import UUID

from nexus_knowledge.retrieval import rerank as policy

logger = logging.getLogger(__name__)

#: ``(session_factory, tenant_id, user_id, model_version_id, purpose) -> reranker``; raises if not allowed.
RerankerFactory = Callable[[Any, UUID, UUID, UUID, str], Any]
_FACTORY: list[RerankerFactory] = []


def set_reranker_factory(factory: RerankerFactory | None) -> None:
    _FACTORY[:] = [factory] if factory else []


@dataclass(frozen=True)
class RerankConfig:
    model_id: UUID
    threshold: float = policy.DEFAULT_THRESHOLD
    top_k: int = 0


def config_of(settings: dict[str, Any] | None) -> RerankConfig | None:
    raw = (settings or {}).get('rerank_config') or {}
    if not raw.get('enabled'):
        return None
    try:
        model = UUID(str(raw.get('model_id') or ''))
    except ValueError:
        return None
    threshold = raw.get('threshold', policy.DEFAULT_THRESHOLD)
    return RerankConfig(model, float(threshold) if isinstance(threshold, (int, float)) else policy.DEFAULT_THRESHOLD,
                        int(raw.get('top_k') or 0))


def validate(settings: dict[str, Any] | None) -> None:
    raw = (settings or {}).get('rerank_config') or {}
    if not raw.get('enabled'):
        return
    if not raw.get('model_id'):
        raise ValueError('rerank_config needs a rerank model (model_id)')
    threshold = raw.get('threshold', policy.DEFAULT_THRESHOLD)
    if not isinstance(threshold, (int, float)) or isinstance(threshold, bool) or not 0 <= threshold <= 1:
        raise ValueError('rerank_config.threshold must be between 0 and 1')
    if not 0 <= int(raw.get('top_k') or 0) <= 50:
        raise ValueError('rerank_config.top_k must be between 0 and 50')


def passage(hit) -> str:
    """Text the model sees: title and heading path before the passage (WeKnora ``ModelPassage``)."""
    header = ' > '.join(hit.section)
    return '\n\n'.join(part for part in (hit.filename, header, hit.content) if part and part.strip())


async def rerank_hits(factory, tenant_id: UUID, user_id: UUID, config: RerankConfig, query: str, hits: list,
                      limit: int) -> tuple[list, policy.Diagnostics]:
    """Reorder ``hits`` (best first) and cut them to ``limit``. Always returns usable hits."""
    diag = policy.Diagnostics(model_id=str(config.model_id), threshold=config.threshold,
                              effective_threshold=config.threshold, candidate_count=len(hits))
    ordered = hits[:limit]
    if not hits:
        diag.outcome = 'no_candidates'
        return ordered, diag
    if not _FACTORY:
        diag.outcome = 'no_model'
        return ordered, diag
    candidates = hits[:policy.MAX_CANDIDATES]
    texts = [policy.fit_passage(passage(hit), 4000) for hit in candidates]
    try:
        client = _FACTORY[0](factory, tenant_id, user_id, config.model_id, 'knowledge.rerank')
    except Exception as exc:  # the user may not use the model, or it is not configured
        diag.outcome, diag.error = 'model_unavailable', type(exc).__name__
        return ordered, diag
    try:
        scores = await client.rerank(query, texts)
    except Exception as exc:
        logger.warning('rerank failed; keeping retrieval order', extra={'error': type(exc).__name__})
        diag.outcome, diag.error = 'model_error', f'{type(exc).__name__}: {exc}'[:300]
        return ordered, diag
    finally:
        await client.close()
    chosen = policy.rerank(scores, [hit.score for hit in candidates], texts, threshold=config.threshold,
                           top_k=min(config.top_k or limit, limit), diag=diag)
    out = []
    for position, item in enumerate(chosen, start=1):
        hit = candidates[item.index]
        hit.score = round(item.score, 6)
        hit.ranks = {**hit.ranks, 'rerank': position}
        out.append(hit)
    return out, diag
