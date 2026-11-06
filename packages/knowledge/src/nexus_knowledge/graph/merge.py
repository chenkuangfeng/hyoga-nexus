"""Conservative merge of per-chunk extractions into one graph (architecture 2.10).

Entities merge only when their normalized names are equal and their types do not conflict: an entity with
no type joins the single typed entity of the same name, but two different types stay two entities. Similar
names are never merged (two securities, people or companies with similar names are different things).
Relations merge by (source, target, direction-free); descriptions are concatenated without duplicates and
capped, weights add up (capped at 10 so one repeated sentence cannot dominate), and every merged element keeps
the chunks it came from so a document change can remove it.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .extract import Extraction, norm

MAX_MERGED_DESCRIPTION = 800
MAX_SOURCES = 20


@dataclass(frozen=True)
class Source:
    chunk_id: str
    version_id: str


@dataclass
class GraphEntity:
    key: str
    name: str
    type: str
    description: str = ''
    sources: list[Source] = field(default_factory=list)
    degree: int = 0


@dataclass
class GraphRelation:
    source: str
    target: str
    description: str = ''
    keywords: list[str] = field(default_factory=list)
    weight: float = 0.0
    sources: list[Source] = field(default_factory=list)


@dataclass
class Graph:
    entities: dict[str, GraphEntity] = field(default_factory=dict)
    relations: dict[tuple[str, str], GraphRelation] = field(default_factory=dict)


def _join(left: str, right: str, limit: int) -> str:
    parts = [p for p in dict.fromkeys(filter(None, (left.split('；') + right.split('；'))))]
    return '；'.join(parts)[:limit]


def _add_source(sources: list[Source], source: Source) -> None:
    if source not in sources and len(sources) < MAX_SOURCES:
        sources.append(source)


def merge(extractions: list[tuple[Source, Extraction]]) -> Graph:
    """Merge extractions in the given order; the result is deterministic for the same input order."""
    graph = Graph()
    typed: dict[str, set[str]] = {}
    for _, extraction in extractions:
        for entity in extraction.entities:
            if entity.type:
                typed.setdefault(norm(entity.name), set()).add(entity.type.casefold())

    def key_of(name: str, kind: str) -> str:
        base = norm(name)
        types = typed.get(base, set())
        if kind:
            return f'{base}|{kind.casefold()}'
        return f'{base}|{next(iter(types))}' if len(types) == 1 else f'{base}|'

    for source, extraction in extractions:
        local: dict[str, str] = {}
        for entity in extraction.entities:
            key = key_of(entity.name, entity.type)
            local[norm(entity.name)] = key
            current = graph.entities.get(key)
            if current is None:
                current = graph.entities[key] = GraphEntity(key, entity.name, entity.type)
            current.description = _join(current.description, entity.description, MAX_MERGED_DESCRIPTION)
            _add_source(current.sources, source)
        for relation in extraction.relations:
            a, b = local.get(norm(relation.source)), local.get(norm(relation.target))
            if a is None or b is None or a == b:
                continue
            pair = (a, b) if a <= b else (b, a)
            current = graph.relations.get(pair)
            if current is None:
                current = graph.relations[pair] = GraphRelation(pair[0], pair[1])
            current.description = _join(current.description, relation.description, MAX_MERGED_DESCRIPTION)
            current.keywords = list(dict.fromkeys([*current.keywords, *relation.keywords]))[:12]
            current.weight = min(10.0, current.weight + relation.weight)
            _add_source(current.sources, source)
    for (a, b), _ in graph.relations.items():
        graph.entities[a].degree += 1
        graph.entities[b].degree += 1
    return graph
