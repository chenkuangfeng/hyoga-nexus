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
from .schedule import schedule_tools
from .skills import skills_tools
from .tool_output import tool_output_tools
from .todo import todo_tool
from .web import web_tools

# These are useful on demand but uncommon on most turns. Keep the frequently used
# conversation, skill loading/execution, knowledge search, and sandbox read/write/exec
# schemas directly available; the gateway exposes these through the existing bridge only
# when their combined schema estimate crosses the agent's threshold.
_DEFERRABLE_BUILTINS = frozenset({
    'propose_memory_draft', 'start_long_term_update', 'read_conversation', 'read_skill_file',
    'skill_manage', 'skill_save', 'skill_rollback', 'grep_chunks', 'document_outline',
    'query_knowledge_graph', 'sandbox_list_files', 'sandbox_search_files', 'sandbox_edit_file',
    'sandbox_exec_async', 'sandbox_job_wait', 'sandbox_job_cancel', 'cronjob_list', 'cronjob_manage',
})


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
        ('schedule', tuple(schedule_tools())),
    ):
        for tool in tools:
            registry.register(RegisteredTool(
                replace(tool.definition, group=group, deferrable=tool.definition.name in _DEFERRABLE_BUILTINS),
                tool.handler, tool.public_result,
            ))
    return registry


def side_effects_by_name():
    """Lookup of whether a builtin tool changes anything outside the platform: ``lookup(name)`` is True or False, or
    None for a tool that is not known (recovery treats an unknown tool as having side effects)."""
    table = {definition.name: bool(definition.side_effects) for definition in builtins().definitions()}
    return table.get
