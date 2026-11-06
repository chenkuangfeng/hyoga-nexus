"""Presentation catalog of builtin tools for the agent editor.

The editor groups tools and shows their impact (reference: WeKnora ``AvailableToolDefinitions`` in
``internal/handler/custom_agent.go``). This module only describes tools; it grants nothing. Binding a
tool to an agent and the gateway's per-call authorization remain the only ways a tool becomes usable.
"""
from __future__ import annotations

from dataclasses import dataclass

from nexus_core.native import BUILTIN_TOOL_NAMES

from .registration import builtins

#: Editor groups in display order. A tool not listed in ``TOOL_GROUPS`` falls into ``base``.
GROUP_ORDER = ('base', 'memory', 'skills')

TOOL_GROUPS: dict[str, str] = {
    'ask_user': 'base', 'todo': 'base', 'update_working_checkpoint': 'base', 'read_tool_output': 'base',
    'read_memory': 'memory', 'search_memory': 'memory', 'propose_memory_draft': 'memory',
    'start_long_term_update': 'memory', 'search_conversations': 'memory', 'read_conversation': 'memory',
    'load_skill': 'skills', 'read_skill_file': 'skills', 'run_skill_script': 'skills',
}


@dataclass(frozen=True)
class CatalogEntry:
    """Public description of one builtin tool; flags mirror its ``ToolDefinition``."""

    name: str
    description: str
    group: str
    #: `read` / `probe` / `write` / `destructive` (tool-call-hardening D10).
    risk: str
    #: Legacy label derived from `risk`, kept one release for existing clients.
    risk_level: str
    read_only: bool
    requires_approval: bool
    side_effects: bool


def builtin_catalog() -> list[CatalogEntry]:
    """Return every registered builtin tool in ``BUILTIN_TOOL_NAMES`` order.

    Names without a registered ``v1`` definition (for example deferred execution tools) are skipped,
    so the editor never offers a tool the worker cannot run.
    """
    registry = builtins()
    entries: list[CatalogEntry] = []
    for name in BUILTIN_TOOL_NAMES:
        tool = registry.get(name, 'v1')
        if tool is None:
            continue
        definition = tool.definition
        entries.append(CatalogEntry(
            name=name, description=definition.description, group=TOOL_GROUPS.get(name, 'base'),
            risk=definition.risk, risk_level=definition.risk_level, read_only=definition.read_only,
            requires_approval=definition.requires_approval, side_effects=definition.side_effects,
        ))
    return entries
