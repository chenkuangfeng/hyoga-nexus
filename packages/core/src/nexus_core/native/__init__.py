"""Compatibility exports for Native configuration and hook contracts."""
from .policy import BUILTIN_TOOL_NAMES, NativePolicy
from .hooks import HookContext, HookTransform

__all__ = [
    'BUILTIN_TOOL_NAMES',
    'NativePolicy',
    'HookContext',
    'HookTransform',
]
