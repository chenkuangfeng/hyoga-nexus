"""Progressive tool loading: `tool_search`, `tool_describe` and `tool_call` (openspec 2026-11-07-tool-expansion, R4).

When the schemas of the *deferrable* tools (MCP tools and tools that declare `deferrable`) would take more than
`defer_min_tokens` of the context, they are not sent to the model. The model sees three bridge tools instead:
it searches a catalog, asks for the schema of the tools it needs, and calls them through `tool_call`. The tool
block therefore never changes inside a Run (provider prompt caches stay valid), unlike designs that add tools
mid-Run. Hermes `tools/tool_search.py` is the model; the bridge never grants anything: `tool_call` unwraps to the
real tool and runs the full gateway pipeline for it (authorization, access level, guard, approval, audit).
"""
from __future__ import annotations

import json
import re

from nexus_core.runtime import ToolDefinition
from nexus_core.schema import sanitize

TOOL_SEARCH, TOOL_DESCRIBE, TOOL_CALL = 'tool_search', 'tool_describe', 'tool_call'
BRIDGE_NAMES = frozenset({TOOL_SEARCH, TOOL_DESCRIBE, TOOL_CALL})
#: Rough characters per token for schema text; only used to decide whether deferral is worth it.
CHARS_PER_TOKEN = 3
MAX_QUERIES, MAX_DESCRIBE, MAX_RESULTS = 7, 10, 10
#: Characters of the catalog embedded in `tool_search`'s own description; beyond it only the group sizes show.
CATALOG_CHARS = 3000
_WORD = re.compile(r'[a-z0-9]+|[一-鿿]')


def estimate_tokens(definition: ToolDefinition) -> int:
    """Estimate schema tokens from compact UTF-8 JSON before provider serialization.

    This is a stable threshold heuristic, not a billing count: tokenizer and provider wrappers
    differ. Avoiding ASCII escaping matters for Chinese descriptions, whose escaped JSON can
    inflate the estimate several-fold without changing the model-visible text.
    """
    payload = json.dumps(definition.parameters, ensure_ascii=False, separators=(',', ':'))
    return (len(definition.name) + len(definition.description) + len(payload)) // CHARS_PER_TOKEN


def is_deferrable(definition: ToolDefinition) -> bool:
    return definition.deferrable or definition.source == 'mcp'


def should_defer(candidates: list[ToolDefinition], min_tokens: int) -> bool:
    """Whether the deferrable tools are heavy enough to hide. 0 turns the feature off."""
    return bool(min_tokens) and sum(estimate_tokens(d) for d in candidates) >= min_tokens


def _words(text: str) -> set[str]:
    return set(_WORD.findall(text.lower()))


def search(catalog: dict[str, ToolDefinition], queries: list[str], limit: int) -> list[str]:
    """Names ranked by how many query words appear in their name and description; an empty query lists all."""
    if not any(q.strip() for q in queries):
        return sorted(catalog)[:limit * 5]
    scored: dict[str, int] = {}
    for query in queries[:MAX_QUERIES]:
        wanted = _words(query)
        for name, definition in catalog.items():
            score = len(wanted & _words(name.replace('_', ' '))) * 3 + len(wanted & _words(definition.description))
            if score:
                scored[name] = max(scored.get(name, 0), score)
    return sorted(scored, key=lambda name: (-scored[name], name))[:limit]


def bridge_definitions(catalog: dict[str, ToolDefinition]) -> list[ToolDefinition]:
    """The three bridge tools. The catalog is listed in `tool_search`'s description (fixed for the Run)."""
    lines, used = [], 0
    for name in sorted(catalog):
        line = f'- {name}: {catalog[name].description.strip().splitlines()[0][:100] if catalog[name].description.strip() else ""}'
        if used + len(line) > CATALOG_CHARS:
            lines.append(f'- ... {len(catalog) - len(lines)} more; search by keyword')
            break
        lines.append(line)
        used += len(line) + 1
    listing = '\n'.join(lines)
    return [
        ToolDefinition(TOOL_SEARCH,
                       'Find additional tools by keyword. These tools are not loaded yet: use tool_describe for the schema, '
                       'then tool_call to run one. Available:\n' + listing,
                       {'type': 'object', 'properties': {
                           'queries': {'type': 'array', 'items': {'type': 'string', 'maxLength': 200}, 'maxItems': MAX_QUERIES},
                           'limit': {'type': 'integer', 'minimum': 1, 'maximum': MAX_RESULTS}},
                        'additionalProperties': False},
                       read_only=True, idempotent=True),
        ToolDefinition(TOOL_DESCRIBE, 'Return the description and parameter schema of tools found with tool_search.',
                       {'type': 'object', 'properties': {'names': {'type': 'array', 'items': {'type': 'string', 'maxLength': 64},
                                                                    'minItems': 1, 'maxItems': MAX_DESCRIBE}},
                        'required': ['names'], 'additionalProperties': False},
                       read_only=True, idempotent=True),
        ToolDefinition(TOOL_CALL, 'Run a tool found with tool_search. Describe it first so the arguments are right.',
                       {'type': 'object', 'properties': {'name': {'type': 'string', 'maxLength': 64},
                                                         'arguments': {'type': 'object'}},
                        'required': ['name', 'arguments'], 'additionalProperties': False},
                       side_effects=True, risk='write'),
    ]


def describe(catalog: dict[str, ToolDefinition], names: list[str]) -> str:
    """Schemas of the named tools as JSON; unknown names are reported, not guessed."""
    parts = []
    for name in names[:MAX_DESCRIBE]:
        definition = catalog.get(name)
        parts.append(json.dumps({'name': name, 'description': definition.description,
                                 'parameters': sanitize(definition.parameters)}, ensure_ascii=False)
                     if definition else f'{name}: not an available tool')
    return '\n'.join(parts)
