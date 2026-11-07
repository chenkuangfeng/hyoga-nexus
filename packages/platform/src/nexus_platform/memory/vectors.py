"""Semantic memory recall: vectors for published versions (openspec 2026-11-06-memory-evolution stage 5, D2).

- The space chooses an embedding model (`memory_space_settings.embedding_model_version_id`). Without one,
  memory search stays keyword only.
- The worker fills `memory_embeddings` for current versions of active entries (`embedding_tick`), with each
  owner's own key (`owner_model_call`, purpose `memory.embedding`). Publishing never waits for it.
- At search time the query is embedded with the searching owner's key and compared in process against
  that owner's vectors of the same model (decision 5); the ranking is fused with the keyword ranking.
  Any failure (no model, no access, provider error) degrades to keyword search and is audited.

The embedding client is injected by the composition root (`set_embedder_factory`), so this platform module
does not depend on a provider SDK. With no factory set, the vector channel is simply absent.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Awaitable, Callable, Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus_core.platform import utc_now
from nexus_memory import semantic
from nexus_platform.persistence.models import (
    MemoryEmbeddingRecord,
    MemoryEntryRecord,
    MemorySpaceSettingsRecord,
    MemoryVersionRecord,
)

logger = logging.getLogger(__name__)

#: Versions embedded per worker tick, and how long an owner whose calls fail is skipped.
TICK_LIMIT = 32
FAILURE_BACKOFF_SECONDS = 3600.0


class Embedder(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]: ...
    async def close(self) -> None: ...


#: `(factory, tenant_id, owner_id, model_version_id) -> Embedder`; raises when the owner cannot use the model.
EmbedderFactory = Callable[[Any, UUID, UUID, UUID], Embedder]
_FACTORY: list[EmbedderFactory] = []
_FAILED: dict[tuple[UUID, UUID], float] = {}


def set_embedder_factory(factory: EmbedderFactory | None) -> None:
    """Install (or remove, with None) the embedding client factory; called once by the worker."""
    _FACTORY[:] = [factory] if factory else []


def embedding_model(db: Session, tenant_id: UUID) -> UUID | None:
    row = db.get(MemorySpaceSettingsRecord, tenant_id)
    return row.embedding_model_version_id if row else None


def owner_vectors(db: Session, tenant_id: UUID, owner_id: UUID, model_id: UUID) -> list[tuple[UUID, list[float]]]:
    """Vectors of the owner's active entries at their current version under `model_id`."""
    rows = db.execute(
        select(MemoryEmbeddingRecord.entry_id, MemoryEmbeddingRecord.vector)
        .join(MemoryEntryRecord, (MemoryEntryRecord.id == MemoryEmbeddingRecord.entry_id)
              & (MemoryEntryRecord.current_version == MemoryEmbeddingRecord.version))
        .where(MemoryEmbeddingRecord.tenant_id == tenant_id, MemoryEmbeddingRecord.owner_user_id == owner_id,
               MemoryEmbeddingRecord.model_version_id == model_id, MemoryEntryRecord.active.is_(True))).all()
    return [(entry_id, list(vector)) for entry_id, vector in rows]


async def vector_ranking(factory: Callable[[], Session], *, tenant_id: UUID, owner_id: UUID,
                         query: str) -> list[UUID] | None:
    """Entry ids nearest to `query` for this owner, or None when the vector channel is unavailable."""
    if not _FACTORY or not query.strip():
        return None
    def load():
        with factory() as db:
            model = embedding_model(db, tenant_id)
            return model, (owner_vectors(db, tenant_id, owner_id, model) if model else [])
    from nexus_platform.runs.dbexec import run_db  # the database call must not stall the Runs sharing this loop
    model_id, vectors = await run_db(load)
    if not model_id or not vectors:
        return None
    embedder = None
    try:
        embedder = _FACTORY[0](factory, tenant_id, owner_id, model_id)
        (query_vector,) = await embedder.embed([query])
    except Exception:  # provider or authorization failure: keyword search still answers
        logger.warning('memory query embedding failed', extra={'tenant_id': str(tenant_id)})
        return None
    finally:
        if embedder is not None:
            await embedder.close()
    return semantic.nearest(query_vector, vectors)


def _missing(db: Session, limit: int) -> list[tuple[UUID, UUID, UUID, int, UUID, str]]:
    """(tenant, owner, entry, version, model, text) of current versions without a vector for their space's model."""
    rows = db.execute(
        select(MemoryEntryRecord.tenant_id, MemoryEntryRecord.owner_user_id, MemoryEntryRecord.id,
               MemoryEntryRecord.current_version, MemorySpaceSettingsRecord.embedding_model_version_id,
               MemoryEntryRecord.topic, MemoryVersionRecord.content)
        .join(MemorySpaceSettingsRecord, MemorySpaceSettingsRecord.tenant_id == MemoryEntryRecord.tenant_id)
        .join(MemoryVersionRecord, (MemoryVersionRecord.entry_id == MemoryEntryRecord.id)
              & (MemoryVersionRecord.version == MemoryEntryRecord.current_version))
        .outerjoin(MemoryEmbeddingRecord, (MemoryEmbeddingRecord.entry_id == MemoryEntryRecord.id)
                   & (MemoryEmbeddingRecord.version == MemoryEntryRecord.current_version)
                   & (MemoryEmbeddingRecord.model_version_id == MemorySpaceSettingsRecord.embedding_model_version_id))
        .where(MemorySpaceSettingsRecord.embedding_model_version_id.is_not(None),
               MemorySpaceSettingsRecord.enabled.is_(True), MemoryEntryRecord.active.is_(True),
               MemoryEmbeddingRecord.entry_id.is_(None))
        .limit(limit * 4)).all()
    now = time.monotonic()
    out = []
    for tenant, owner, entry, version, model, topic, content in rows:
        if now - _FAILED.get((tenant, owner), -FAILURE_BACKOFF_SECONDS * 2) < FAILURE_BACKOFF_SECONDS:
            continue
        out.append((tenant, owner, entry, version, model, semantic.embeddable_text(topic, content)))
        if len(out) >= limit:
            break
    return out


async def embedding_tick(factory: Callable[[], Session]) -> int:
    """Embed up to `TICK_LIMIT` versions that lack a vector; returns how many vectors were stored."""
    if not _FACTORY:
        return 0
    with factory() as db:
        pending = _missing(db, TICK_LIMIT)
    groups: dict[tuple[UUID, UUID, UUID], list[tuple[UUID, int, str]]] = {}
    for tenant, owner, entry, version, model, text in pending:
        groups.setdefault((tenant, owner, model), []).append((entry, version, text))
    stored = 0
    for (tenant, owner, model), items in groups.items():
        embedder = None
        try:
            embedder = _FACTORY[0](factory, tenant, owner, model)
            vectors = await embedder.embed([text for _, _, text in items])
        except Exception:
            _FAILED[(tenant, owner)] = time.monotonic()
            logger.warning('memory embedding failed; owner skipped for an hour', extra={'tenant_id': str(tenant)})
            continue
        finally:
            if embedder is not None:
                await embedder.close()
        with factory() as db, db.begin():
            for (entry, version, _), vector in zip(items, vectors):
                if db.get(MemoryEmbeddingRecord, (entry, version, model)) is None:
                    db.add(MemoryEmbeddingRecord(entry_id=entry, version=version, model_version_id=model,
                                                 tenant_id=tenant, owner_user_id=owner, dims=len(vector),
                                                 vector=[float(x) for x in vector], created_at=utc_now()))
                    stored += 1
    return stored


def reset_failures() -> None:
    """Forget failed owners (tests, and after the space changes its model)."""
    _FAILED.clear()


AsyncTick = Callable[[Callable[[], Session]], Awaitable[int]]
