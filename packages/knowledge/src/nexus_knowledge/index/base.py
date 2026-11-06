"""Vector store port (openspec 2026-11-06-knowledge-base K1, decision 1).

Every vector engine (SQLite, PostgreSQL pgvector, Qdrant, Elasticsearch, Milvus, and later others) implements
:class:`VectorIndex`. One instance talks to one registered vector store; a knowledge base writes into the
``collection`` derived from its id, so knowledge bases never share index rows.

Security contract (architecture 2.10, Pre-Filter): both search methods receive ``scope``, the document
version ids the caller may read **right now**, computed in the platform database before any search. Each
engine applies it as a server-side filter of the query itself; an engine must never search globally and
filter afterwards, and an empty scope returns no candidates without contacting the engine.

Rows are derived data. The text of a chunk lives in the platform database; engines keep the chunk id, its
knowledge base and document version, the vector and the keyword tokens (``nexus_knowledge.text.tokenize``).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from ..retrieval.fuse import Candidate


class VectorStoreError(RuntimeError):
    """Engine failure (connection, protocol, missing extension). ``code`` is a stable reason for diagnosis."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class IndexRow:
    chunk_id: str
    kb_id: str
    version_id: str
    tokens: str
    vector: Sequence[float] | None = None


@dataclass(frozen=True, slots=True)
class Scope:
    """Pre-Filter result for one search: readable version ids of one knowledge base (collection)."""

    kb_id: str
    version_ids: tuple[str, ...]


class VectorIndex(ABC):
    """One registered vector store. Implementations are safe to reuse across requests."""

    #: Engine key, matching the capability catalog (``vector_engine`` group).
    engine: str = ''
    #: False when the engine cannot serve the keyword channel (the search then uses vectors only).
    supports_keyword: bool = True
    #: True when every row needs a vector: knowledge bases on this engine must have an embedding model.
    requires_vectors: bool = False

    @abstractmethod
    async def ping(self) -> dict[str, Any]:
        """Connection test: returns engine details (version, features). Raises :class:`VectorStoreError`."""

    @abstractmethod
    async def upsert(self, collection: str, rows: Sequence[IndexRow], *, dimension: int | None) -> None:
        """Insert or replace rows by ``chunk_id``. ``dimension`` is the embedding size (None: keyword only)."""

    @abstractmethod
    async def delete_versions(self, collection: str, version_ids: Sequence[str]) -> None:
        """Remove every row of the given document versions."""

    @abstractmethod
    async def drop_collection(self, collection: str) -> None:
        """Remove every row of a knowledge base."""

    @abstractmethod
    async def search_vector(self, collection: str, query: Sequence[float], scope: Scope, k: int) -> list[Candidate]:
        """Cosine similarity in [0, 1] (higher is closer), restricted to ``scope`` by the engine."""

    @abstractmethod
    async def search_keyword(self, collection: str, tokens: Sequence[str], scope: Scope, k: int) -> list[Candidate]:
        """Keyword relevance (any positive scale), restricted to ``scope`` by the engine."""

    async def close(self) -> None:  # pragma: no cover - engines without resources
        return None


def collection_name(kb_id: str) -> str:
    """Collection/index name of a knowledge base: ``kb_`` + id without dashes (valid for every engine)."""
    return 'kb_' + kb_id.replace('-', '').lower()


#: ``engine -> factory(connection_config, index_config) -> VectorIndex``; filled by engine modules.
FACTORIES: dict[str, Any] = {}


def register_engine(engine: str, factory: Any, *, verified: bool) -> None:
    """Register an engine implementation and mark it available in the capability catalog."""
    from .. import capabilities

    FACTORIES[engine] = factory
    capabilities.mark_available('vector_engine', engine, verified=verified)


def open_index(engine: str, connection: Mapping[str, Any], index: Mapping[str, Any] | None = None) -> VectorIndex:
    try:
        factory = FACTORIES[engine]
    except KeyError:
        from .. import capabilities

        capabilities.require_available('vector_engine', engine)
        raise
    return factory(dict(connection), dict(index or {}))
