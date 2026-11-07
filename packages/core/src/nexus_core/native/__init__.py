"""Compatibility exports for Native configuration and hook contracts."""
from .policy import BUILTIN_TOOL_NAMES, KNOWLEDGE_TOOL_NAMES, NativePolicy
from .tool_groups import GROUP_IDS, TOOL_GROUPS, ToolGroup, group_enabled, group_of
from .hooks import HookContext, HookTransform

__all__ = [
    'GROUP_IDS',
    'TOOL_GROUPS',
    'ToolGroup',
    'group_enabled',
    'group_of',
    'BUILTIN_TOOL_NAMES',
    'KNOWLEDGE_TOOL_NAMES',
    'NativePolicy',
    'HookContext',
    'HookTransform',
]
