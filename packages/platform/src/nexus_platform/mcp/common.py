"""Shared constants/helpers for the MCP domain modules."""
from __future__ import annotations

#: Resource kind used in ``platform_resources`` / ``agent_resource_bindings`` for MCP services.
RESOURCE_KIND = "mcp_service"

# Re-exported so the MCP modules share one UTC-normalisation rule for SQLite's naive datetimes.
from nexus_platform.auth.sessions import aware  # noqa: E402,F401

__all__ = ["RESOURCE_KIND", "aware"]
