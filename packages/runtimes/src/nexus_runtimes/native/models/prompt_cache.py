"""Deterministic wire values and bounded Anthropic prompt-cache breakpoints.

Adapted from GenericAgent llmcore.py's ClaudeSession message markers. Only the official
Messages protocol receives ephemeral hints; other protocols remain vendor-neutral.
"""
from __future__ import annotations

import json
from typing import Any, Sequence

from nexus_core.runtime import ToolDefinition


def ordered_tools(tools: Sequence[ToolDefinition]) -> tuple[ToolDefinition, ...]:
    """Keep the wire tool prefix stable without modifying Run-owned definitions."""
    return tuple(sorted(tools, key=lambda tool: tool.name))


def canonical_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Copy JSON schema with recursively sorted object keys; preserve every array's order.

    Equivalent schemas arriving through different registration paths must serialize identically.
    Arrays (required, enum, oneOf, etc.) remain untouched to avoid changing their meaning.
    """
    return json.loads(json.dumps(schema, ensure_ascii=False, sort_keys=True, allow_nan=False))


def mark_anthropic_cache(payload: dict[str, Any]) -> None:
    """Mark up to four boundaries in a freshly built Messages payload, never source messages.

    The stable tools/system prefix has its own boundary even when the conversation suffix
    changes. Two rolling message boundaries retain opportunities across adjacent turns.
    No model-name guesses, persistent cache types, credentials or cache routing IDs are used.
    """
    if payload.get('tools'):
        payload['tools'][-1]['cache_control'] = {'type': 'ephemeral'}
    if payload.get('system'):
        payload['system'] = [{'type': 'text', 'text': payload['system'],
                              'cache_control': {'type': 'ephemeral'}}]
    for message in payload['messages'][-2:]:
        message['content'][-1]['cache_control'] = {'type': 'ephemeral'}
