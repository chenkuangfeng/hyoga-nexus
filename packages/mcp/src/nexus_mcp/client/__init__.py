"""MCP client: connection validation, fingerprints, discovery, invocation and a stdio session pool."""
from .config import (
    TRANSPORTS,
    assert_resolved,
    fingerprint,
    illegal_header_value_reason,
    is_secret_reference,
    new_epoch,
    normalize_headers,
    validate_config,
    validate_header_value,
)
from .discovery import MCPToolSpec, StdioSessionPool, call, discover, validate_output
from .errors import (
    McpCallRejected,
    McpConnectionError,
    McpDiscoveryTimeout,
    McpError,
    McpOutputSchemaError,
    McpServiceDisabled,
    McpUnavailable,
)
from .names import external_description, registered_name, sanitize_name, tool_ref, valid_external_tool_name

__all__ = [
    "TRANSPORTS",
    "assert_resolved",
    "fingerprint",
    "illegal_header_value_reason",
    "is_secret_reference",
    "new_epoch",
    "normalize_headers",
    "validate_config",
    "validate_header_value",
    "MCPToolSpec",
    "StdioSessionPool",
    "call",
    "discover",
    "validate_output",
    "McpCallRejected",
    "McpConnectionError",
    "McpDiscoveryTimeout",
    "McpError",
    "McpOutputSchemaError",
    "McpServiceDisabled",
    "McpUnavailable",
    "external_description",
    "registered_name",
    "sanitize_name",
    "tool_ref",
    "valid_external_tool_name",
]
