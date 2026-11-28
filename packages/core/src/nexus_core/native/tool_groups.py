"""Tool groups: the unit the agent editor shows and the user switches on or off
(openspec 2026-11-07-tool-expansion, R1).

A group is offered to a Run only when two layers agree: the group is *available* (a deployment-side fact the
platform decides: sandbox accepted, search backend configured, Wiki base bound...) and the agent has it
*enabled* (`NativePolicy.tool_groups_enabled`, falling back to `default_enabled`). The switch can only
narrow what binding and per-call authorization already allow. This module holds the data only; availability
needs the database and lives in `nexus_platform.runs.tool_gates`.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ToolGroup:
    """One editor group. `planned` names the phase that delivers its tools; empty when they exist."""
    id: str
    label: str
    default_enabled: bool = True
    #: Always on and cannot be switched off (`base` holds the tools a Run cannot work without).
    locked: bool = False
    planned: str = ''


#: Display order. High-impact groups (`web`, `collab`, `schedule`, `media`) default to off, so an
#: agent version saved before a group existed never gains its tools.
TOOL_GROUPS: tuple[ToolGroup, ...] = (
    ToolGroup('base', '基础工具', locked=True),
    ToolGroup('memory', '记忆'),
    ToolGroup('knowledge', '知识库'),
    ToolGroup('skills', '技能'),
    # Kept as an internal execution-availability gate for compatibility. The
    # sandbox-backed terminal and file tools are presented under `base`; the
    # sandbox profile still controls whether those tools can run.
    ToolGroup('sandbox', '执行环境', default_enabled=True),
    ToolGroup('wiki', 'Wiki', planned='知识库 K6.1'),
    ToolGroup('web', 'Web', default_enabled=False, planned='工具扩展 E'),
    ToolGroup('collab', '协作', default_enabled=False, planned='工具扩展 G'),
    ToolGroup('schedule', '定时', default_enabled=False, planned='工具扩展 G'),
    ToolGroup('media', '多媒体', default_enabled=False, planned='工具扩展 G'),
    ToolGroup('mcp', 'MCP 工具', default_enabled=False),
)
GROUP_IDS = tuple(group.id for group in TOOL_GROUPS)
_BY_ID = {group.id: group for group in TOOL_GROUPS}


def group_of(group_id: str) -> ToolGroup | None:
    """The group with this id, or None for an unknown id."""
    return _BY_ID.get(group_id)


def group_enabled(switches: dict[str, bool] | None, group_id: str) -> bool:
    """Whether the agent's switches leave `group_id` on.

    The sandbox id remains an internal deployment gate, not an agent-selectable group;
    old saved false switches are ignored. Deployment availability still filters it.
    """
    group = _BY_ID.get(group_id)
    if group is None:
        return False
    if group.locked or group_id == 'sandbox':
        return True
    return bool((switches or {}).get(group_id, group.default_enabled))
