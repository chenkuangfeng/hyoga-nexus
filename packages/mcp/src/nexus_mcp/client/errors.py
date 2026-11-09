"""Stable error classification for MCP client operations.

The codes here are the ones the platform and gateway surface to callers; the message strings are
model-facing and safe to show (they never embed credential values or raw connection details).
"""
from __future__ import annotations

import re


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


class McpUnauthorized(McpError):
    """The resource server answered 401; the platform may refresh the OAuth token once and retry.

    Internal to the client/platform boundary: it never reaches the model as a final result,
    because after the single refresh-and-retry the caller reports a stable OAuth error instead.
    """

    code = "mcp_unauthorized"


def is_unauthorized(exc: BaseException) -> bool:
    """True when `exc` (or its cause chain) is an HTTP 401 / authorization challenge.

    The MCP SDK wraps transport failures differently by version and transport, so this inspects
    the exception chain for a status code first and only then the message text.
    """
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if getattr(current, "status_code", None) == 401:
            return True
        response = getattr(current, "response", None)
        if getattr(response, "status_code", None) == 401:
            return True
        text = str(current)
        if re.search(r"\b401\b", text) or "unauthorized" in text.casefold():
            return True
        current = current.__cause__ or current.__context__
    return False
