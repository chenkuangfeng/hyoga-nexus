"""Application-safe tool composition; deferred host execution tools are never registered."""
from nexus_tools.registry import ToolRegistry
from .ask_user import ask_user_tool
from .checkpoint import checkpoint_tool
from .memory import memory_tools


def builtins(store):
    """Build a fresh registry; every exposed call still requires binding and live authorization."""
    registry = ToolRegistry()
    for tool in (ask_user_tool(), checkpoint_tool(store), *memory_tools(store)):
        registry.register(tool)
    return registry
