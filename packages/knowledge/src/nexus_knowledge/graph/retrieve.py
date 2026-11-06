"""Bounded graph expansion and rendering (architecture 2.10: graph retrieval is bounded and says so).

Seeds are the entities a query matched. Expansion walks the relations breadth first, strongest relations
first, and stops at the first of: ``hops``, ``max_entities``, ``max_relations``. When a limit cut the walk,
``truncated`` is true and the rendered text says so - an absent relation must not be read as "does not
exist". Rendering is cut to a character budget in the same way.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping


@dataclass(frozen=True)
class Limits:
    hops: int = 2
    max_entities: int = 30
    max_relations: int = 40
    max_chars: int = 6000


@dataclass
class Expansion:
    entity_ids: list[str] = field(default_factory=list)
    relation_ids: list[str] = field(default_factory=list)
    truncated: bool = False


def expand(seeds: list[str], edges: Mapping[str, list[tuple[str, str, float]]], limits: Limits) -> Expansion:
    """``edges[entity] = [(relation_id, other_entity, weight)]``. Deterministic: ties break on ids."""
    result = Expansion()
    seen_entities: set[str] = set()
    seen_relations: set[str] = set()
    frontier: list[str] = []
    for seed in seeds:
        if seed not in seen_entities:
            if len(result.entity_ids) >= limits.max_entities:
                result.truncated = True
                break
            seen_entities.add(seed)
            result.entity_ids.append(seed)
            frontier.append(seed)
    for _ in range(max(0, limits.hops)):
        next_frontier: list[str] = []
        for entity in frontier:
            for relation_id, other, _weight in sorted(edges.get(entity, ()), key=lambda e: (-e[2], e[0])):
                if relation_id in seen_relations:
                    continue
                if len(result.relation_ids) >= limits.max_relations:
                    result.truncated = True
                    continue
                if other not in seen_entities:
                    if len(result.entity_ids) >= limits.max_entities:
                        result.truncated = True
                        continue
                    seen_entities.add(other)
                    result.entity_ids.append(other)
                    next_frontier.append(other)
                seen_relations.add(relation_id)
                result.relation_ids.append(relation_id)
        frontier = next_frontier
        if not frontier:
            break
    else:
        if any(edges.get(entity) for entity in frontier):
            result.truncated = True
    return result


def fit(blocks: list[str], max_chars: int) -> tuple[list[str], bool]:
    """Whole blocks that fit the budget, in order, and whether any were left out."""
    used, kept = 0, []
    for block in blocks:
        if used + len(block) > max_chars:
            return kept, True
        kept.append(block)
        used += len(block)
    return kept, False
