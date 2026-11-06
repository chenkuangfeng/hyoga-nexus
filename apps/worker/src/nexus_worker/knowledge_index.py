"""Worker side of knowledge bases (openspec 2026-11-06-knowledge-base K1.5).

- :func:`install_embedder` gives platform knowledge indexing and search an embedding client built from the
  caller's own key (``owner_model_call``; purpose ``knowledge.embedding`` for indexing with the creator's
  key, ``knowledge.query`` for a search with the searcher's key).
- :func:`knowledge_tick` runs due index and cleanup jobs, at most ``[knowledge].index_concurrency`` per tick,
  when no Run is waiting.
"""
from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session, sessionmaker


def knowledge_embedder(factory, tenant_id: UUID, user_id: UUID, model_version_id: UUID, purpose: str):
    from nexus_platform.models.provider_settings import owner_model_call
    from nexus_runtimes.native.models.embeddings import create_embedder
    call = owner_model_call(factory, tenant_id=tenant_id, owner_id=user_id, version_id=model_version_id,
                            purpose=purpose, model_type='embedding')
    return create_embedder(model=call.model_name, api_key=call.lease.reveal_for_call(), options=call.options,
                           share_connections=True)


def install_embedder() -> None:
    from nexus_platform.knowledge.embedding import set_embedder_factory
    set_embedder_factory(knowledge_embedder)


def knowledge_tick(factory: sessionmaker[Session], loop, concurrency: int) -> bool:
    """Run up to ``concurrency`` due knowledge jobs; True when any ran."""
    import nexus_knowledge.index  # noqa: F401  (registers the vector engines)
    from nexus_platform.knowledge.jobs import run_due
    return loop.run_until_complete(run_due(factory, concurrency)) > 0
