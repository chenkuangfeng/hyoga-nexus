"""Stable error classification for MCP client operations.

The codes here are the ones the platform and gateway surface to callers; the message strings are
model-facing and safe to show (they never embed credential values or raw connection details).
"""
from __future__ import annotations


class McpError(Exception):
    """Base for MCP client failures carrying a stable, non-secret error code."""

    code = "mcp_error"

    def __init__(self, message: str, *, code: str | None = None):
        super().__init__(message)
        if code is not None:
            self.code = code


class McpConnectionError(McpError):
    """The external service could not be reached or the session could not be established."""

    code = "mcp_connection_failed"


class McpDiscoveryTimeout(McpError):
    """Listing tools exceeded the discovery budget."""

    code = "mcp_discovery_timeout"


class McpCallRejected(McpError):
    """The server refused the call; the model should fix its arguments (types, required, nesting)."""

    code = "mcp_call_rejected"


class McpOutputSchemaError(McpError):
    """The call was accepted but its output does not match the declared schema; do not retry with new arguments."""

    code = "mcp_output_schema_failed"


class McpServiceDisabled(McpError):
    """The service is disabled; raised before any connection is attempted."""

    code = "mcp_service_disabled"


class McpUnavailable(McpError):
    """The tool is not currently available (not enabled, removed, or revalidation failed)."""

    code = "mcp_unavailable"
