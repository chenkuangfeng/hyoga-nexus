"""Application-safe tool composition; deferred host execution tools are never registered."""
from dataclasses import replace
from functools import lru_cache

from nexus_tools.registry import RegisteredTool, ToolRegistry
from .ask_user import ask_user_tool
from .checkpoint import checkpoint_tool
from .collab import collab_tools
from .conversations import conversation_tools
from .knowledge import knowledge_tools
from .media import media_tools
from .memory import memory_tools
from .sandbox import sandbox_tools
from .skills import skills_tools
from .tool_output import tool_output_tools
from .todo import todo_tool
from .web import web_tools


@lru_cache(maxsize=1)
def builtins() -> ToolRegistry:
    """Return the process-wide registry of builtin tools (built once, then shared).

    Tool definitions carry no Run state. Handlers take the Run's store from
    ``ToolContext.services``, and every call still requires binding and live authorization.
    Callers must not mutate the returned registry.
    """
    registry = ToolRegistry()
    # The group is chosen where a tool is registered, so a tool cannot be registered without one and the
    # editor, the gates and the registry always agree (openspec 2026-11-07-tool-expansion, R1).
    for group, tools in (
        ('base', (ask_user_tool(), checkpoint_tool(), todo_tool(), *tool_output_tools())),
        ('memory', (*memory_tools(), *conversation_tools())),
        ('skills', tuple(skills_tools())),
        ('knowledge', tuple(knowledge_tools())),
        ('sandbox', tuple(sandbox_tools())),
        ('web', tuple(web_tools())),
        ('collab', tuple(collab_tools())),
        ('media', tuple(media_tools())),
    ):
        for tool in tools:
            registry.register(RegisteredTool(replace(tool.definition, group=group), tool.handler, tool.public_result))
    return registry
