"""Presentation catalog of builtin tools for the agent editor.

The editor groups tools and shows their impact (reference: WeKnora ``AvailableToolDefinitions`` in
``internal/handler/custom_agent.go``). This module only describes tools; it grants nothing. Binding a
tool to an agent and the gateway's per-call authorization remain the only ways a tool becomes usable.
"""
from __future__ import annotations

from dataclasses import dataclass

from nexus_core.native import BUILTIN_TOOL_NAMES, GROUP_IDS, TOOL_GROUPS

from .registration import builtins

#: Editor groups in display order; their definitions live in ``nexus_core.native.tool_groups``. Which group a
#: tool belongs to is declared where it is registered (``registration.builtins``) and read from its definition.
GROUP_ORDER = GROUP_IDS


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
            name=name, description=definition.description, group=definition.group,
            risk=definition.risk, risk_level=definition.risk_level, read_only=definition.read_only,
            requires_approval=definition.requires_approval, side_effects=definition.side_effects,
        ))
    return entries


def group_catalog() -> list[dict]:
    """Every editor group in display order, including groups whose tools are not delivered yet.

    `tool_count` is what the worker can run now; a group with none shows its `planned` phase instead, so the
    editor can render it as a disabled "planned" section rather than hiding it.
    """
    counts: dict[str, int] = {}
    for entry in builtin_catalog():
        counts[entry.group] = counts.get(entry.group, 0) + 1
    return [{'id': group.id, 'label': group.label, 'default_enabled': group.default_enabled, 'locked': group.locked,
             'tool_count': counts.get(group.id, 0), 'planned': group.planned if not counts.get(group.id) else ''}
            for group in TOOL_GROUPS]
