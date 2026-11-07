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


async def knowledge_completer(factory, tenant_id: UUID, user_id: UUID, model_version_id: UUID, purpose: str,
                               system: str, user_text: str, max_tokens: int) -> str:
    """One chat completion with the caller's own key; used for graph extraction and community reports."""
    from nexus_core.runtime import ModelMessage, ModelRequest
    from nexus_platform.errors import NotFound
    from nexus_platform.models.provider_settings import owner_model_call
    from nexus_runtimes.native.models.factory import create_model  # noqa: F401  (same factory memory capture uses)
    from nexus_worker.memory_capture import SUPPORTED_PROTOCOLS, _collect
    call = owner_model_call(factory, tenant_id=tenant_id, owner_id=user_id, version_id=model_version_id,
                            purpose=purpose, model_type='chat')
    if call.options.get('protocol') not in SUPPORTED_PROTOCOLS:
        raise NotFound('Model unavailable')
    model = create_model(model=call.model_name, api_key=call.lease.reveal_for_call(), options=call.options,
                         share_connections=True)
    request = ModelRequest(messages=(ModelMessage(role='system', content=system),
                                     ModelMessage(role='user', content=user_text)),
                           tools=(), max_output_tokens=max_tokens)
    from nexus_platform.runs.model_limits import background_limiter
    async with background_limiter().aslot(call.model_name):  # model_limits: background calls share a provider's limit
        return await _collect(model, request)


def knowledge_vision(factory, tenant_id: UUID, user_id: UUID, model_version_id: UUID, purpose: str):
    from nexus_platform.models.provider_settings import owner_model_call
    from nexus_runtimes.native.models.media import create_vision
    call = owner_model_call(factory, tenant_id=tenant_id, owner_id=user_id, version_id=model_version_id,
                            purpose=purpose, model_type='vision')
    return create_vision(model=call.model_name, api_key=call.lease.reveal_for_call(), options=call.options,
                         share_connections=True)


def knowledge_speech(factory, tenant_id: UUID, user_id: UUID, model_version_id: UUID, purpose: str):
    from nexus_platform.models.provider_settings import owner_model_call
    from nexus_runtimes.native.models.media import create_transcriber
    call = owner_model_call(factory, tenant_id=tenant_id, owner_id=user_id, version_id=model_version_id,
                            purpose=purpose, model_type='speech')
    return create_transcriber(model=call.model_name, api_key=call.lease.reveal_for_call(), options=call.options,
                              share_connections=True)


def knowledge_reranker(factory, tenant_id: UUID, user_id: UUID, model_version_id: UUID, purpose: str):
    from nexus_platform.models.provider_settings import owner_model_call
    from nexus_runtimes.native.models.rerank import create_reranker
    call = owner_model_call(factory, tenant_id=tenant_id, owner_id=user_id, version_id=model_version_id,
                            purpose=purpose, model_type='rerank')
    return create_reranker(model=call.model_name, api_key=call.lease.reveal_for_call(), options=call.options,
                           share_connections=True)


def install_embedder() -> None:
    from nexus_platform.knowledge.embedding import set_embedder_factory
    from nexus_platform.knowledge.graph.llm import set_completer
    set_embedder_factory(knowledge_embedder)
    set_completer(knowledge_completer)
    from nexus_platform.knowledge.media import set_media_factory
    set_media_factory(vision=knowledge_vision, speech=knowledge_speech)
    from nexus_platform.knowledge.rerank import set_reranker_factory
    set_reranker_factory(knowledge_reranker)
    from nexus_platform.knowledge.parsers import set_http_client_factory
    from nexus_runtimes.native.models.network import provider_client
    set_http_client_factory(lambda url: provider_client(url, timeout=600))


def knowledge_tick(factory: sessionmaker[Session], loop, concurrency: int) -> bool:
    """Run up to ``concurrency`` due knowledge jobs; True when any ran."""
    import nexus_knowledge.index  # noqa: F401  (registers the vector engines)
    from nexus_platform.knowledge.graph.build import run_due as run_graph_due
    from nexus_platform.knowledge.jobs import run_due
    from nexus_platform.knowledge.faq import index_tick as faq_tick
    if loop.run_until_complete(run_due(factory, concurrency)) > 0:
        return True
    if loop.run_until_complete(faq_tick(factory)) > 0:
        return True
    from nexus_platform.knowledge.wiki_ingest import index_tick as wiki_tick
    if loop.run_until_complete(wiki_tick(factory)) > 0:
        return True
    return loop.run_until_complete(run_graph_due(factory, 1)) > 0
