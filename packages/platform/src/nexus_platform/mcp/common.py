"""Shared constants/helpers for the MCP domain modules."""
from __future__ import annotations

#: Resource kind used in ``platform_resources`` / ``agent_resource_bindings`` for MCP services.
RESOURCE_KIND = "mcp_service"

#: The read-only tool face an outbound MCP endpoint may expose (openspec 2026-11-08-mcp, decision 2).
#: Full definitions live in :mod:`nexus_platform.mcp.stateless`; this set is the whitelist boundary.
READ_ONLY_TOOL_NAMES = frozenset({
    # knowledge
    "grep_chunks", "document_outline", "query_knowledge_graph", "search_knowledge",
    "read_document", "list_documents",
    # web
    "web_search", "web_fetch",
    # skills
    "load_skill", "read_skill_file", "skill_search",
    # memory
    "read_memory", "search_memory",
    # conversations
    "search_conversations", "read_conversation",
})

# Re-exported so the MCP modules share one UTC-normalisation rule for SQLite's naive datetimes.
from nexus_platform.auth.sessions import aware  # noqa: E402,F401

__all__ = ["RESOURCE_KIND", "READ_ONLY_TOOL_NAMES", "aware"]
