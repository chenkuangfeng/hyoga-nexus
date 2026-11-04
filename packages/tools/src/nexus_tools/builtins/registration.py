"""Application-safe tool composition; deferred host execution tools are never registered."""
from functools import lru_cache

from nexus_tools.registry import ToolRegistry
from .ask_user import ask_user_tool
from .checkpoint import checkpoint_tool
from .memory import memory_tools
from .tool_output import tool_output_tools
from .todo import todo_tool


@lru_cache(maxsize=1)
def builtins() -> ToolRegistry:
    """Return the process-wide registry of builtin tools (built once, then shared).

    Tool definitions carry no Run state. Handlers take the Run's store from
    ``ToolContext.services``, and every call still requires binding and live authorization.
    Callers must not mutate the returned registry.
    """
    registry = ToolRegistry()
    for tool in (ask_user_tool(), checkpoint_tool(), todo_tool(), *memory_tools(), *tool_output_tools()):
        registry.register(tool)
    return registry
