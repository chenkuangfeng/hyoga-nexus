"""Embedding clients for knowledge indexing and queries (openspec 2026-11-06-knowledge-base, decision 6).

The composition roots (API and worker) install a factory with :func:`set_embedder_factory`, so this module
does not depend on a provider SDK. Indexing embeds with the knowledge base creator's key; a query embeds
with the searching user's own key. Without a factory, or when the user cannot use the model, the vector
channel is unavailable and search degrades to keywords.
"""
from __future__ import annotations

from typing import Any, Callable, Protocol
from uuid import UUID


class Embedder(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]: ...
    async def close(self) -> None: ...


#: ``(session_factory, tenant_id, user_id, model_version_id, purpose) -> Embedder``; raises when not allowed.
EmbedderFactory = Callable[[Any, UUID, UUID, UUID, str], Embedder]
_FACTORY: list[EmbedderFactory] = []


def set_embedder_factory(factory: EmbedderFactory | None) -> None:
    _FACTORY[:] = [factory] if factory else []


def embedder(session_factory: Any, tenant_id: UUID, user_id: UUID, model_version_id: UUID, purpose: str) -> Embedder:
    """An embedding client, or ``LookupError`` when no factory is installed."""
    if not _FACTORY:
        raise LookupError('no embedding client is configured')
    return _FACTORY[0](session_factory, tenant_id, user_id, model_version_id, purpose)
