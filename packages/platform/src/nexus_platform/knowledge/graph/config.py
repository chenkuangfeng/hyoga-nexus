"""Graph configuration of a knowledge base (``knowledge_bases.settings['graph']``).

``{"mode": "graphrag_light" | "graphrag_general" | "entity", "store": "builtin" | <graph store id>,
"model_id": <chat model version id>, "entity_types": [...], "relation_types": [...], "instructions": "..."}``.
Validated when a base is created or updated; the capability catalog decides which modes and stores exist.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from nexus_knowledge import capabilities
from nexus_knowledge.graph.extract import Schema

MODES = ('entity', 'graphrag_light', 'graphrag_general')
MAX_TYPES = 30


@dataclass(frozen=True)
class GraphConfig:
    mode: str
    store: str
    model_id: UUID
    schema: Schema


def parse(settings: dict[str, Any] | None, *, require_available: bool = True) -> GraphConfig:
    raw = (settings or {}).get('graph') or {}
    if not isinstance(raw, dict):
        raise ValueError('graph settings must be an object')
    mode = str(raw.get('mode') or 'graphrag_light')
    if mode not in MODES:
        raise ValueError(f'graph mode must be one of {", ".join(MODES)}')
    store = str(raw.get('store') or 'builtin')
    try:
        model = UUID(str(raw.get('model_id') or ''))
    except ValueError:
        raise ValueError('graph indexing needs a chat model (graph.model_id)') from None

    def types(key: str) -> tuple[str, ...]:
        value = raw.get(key) or []
        if not isinstance(value, list) or len(value) > MAX_TYPES:
            raise ValueError(f'graph.{key} must be a list of at most {MAX_TYPES} names')
        return tuple(dict.fromkeys(str(item).strip()[:64] for item in value if str(item).strip()))

    schema = Schema(types('entity_types'), types('relation_types'), str(raw.get('instructions') or '')[:4000])
    if require_available:
        capabilities.require_available('graph_mode', mode)
        capabilities.require_available('graph_store', 'builtin' if store == 'builtin' else 'neo4j')
    return GraphConfig(mode, store, model, schema)
