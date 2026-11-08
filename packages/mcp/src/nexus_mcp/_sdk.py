"""MCP SDK adapter: the only module allowed to import ``mcp.*``.

Nexus pins the official ``mcp`` SDK to 2.x but isolates every SDK import behind
this module so a future 3.x bump only touches this file and the dependency
upper bound. Version differences are probed at import time with a graceful
fallback, mirroring hermes-agent ``_import_sdk_names`` / ``sdk_httpx()``.

Known 1.x -> 2.x break points:
- ``mcp.server.fastmcp.FastMCP`` was renamed to ``mcp.server.MCPServer``.
- The deprecated ``streamablehttp_client`` alias was dropped in 2.0; the
  canonical name is ``streamable_http_client`` (available since 1.24).
- The transport layer moved from ``httpx`` to ``httpx2``; every object crossing
  the SDK boundary (AsyncClient, auth requests, exceptions) must come from the
  module the SDK itself imports.
"""
from __future__ import annotations

from typing import Any

# --- client session / stdio -------------------------------------------------
try:
    from mcp import ClientSession, StdioServerParameters
except ImportError:  # pragma: no cover - SDK absent
    ClientSession = None  # type: ignore[assignment,misc]
    StdioServerParameters = None  # type: ignore[assignment,misc]

try:
    from mcp.client.stdio import stdio_client
except ImportError:  # pragma: no cover - SDK absent
    stdio_client = None  # type: ignore[assignment]

# --- streamable HTTP ---------------------------------------------------------
try:
    from mcp.client.streamable_http import streamable_http_client
except ImportError:  # pragma: no cover - mcp < 1.24 deprecated alias
    try:
        from mcp.client.streamable_http import streamablehttp_client as streamable_http_client
    except ImportError:  # pragma: no cover - SDK absent
        streamable_http_client = None  # type: ignore[assignment]

# --- SSE ---------------------------------------------------------------------
try:
    from mcp.client.sse import sse_client
except ImportError:  # pragma: no cover - SDK absent
    sse_client = None  # type: ignore[assignment]

# --- server ------------------------------------------------------------------
try:
    from mcp.server import MCPServer
except ImportError:  # pragma: no cover - mcp < 2
    try:
        from mcp.server.fastmcp import FastMCP as MCPServer
    except ImportError:  # pragma: no cover - SDK absent
        MCPServer = None  # type: ignore[assignment]

# --- protocol constants ------------------------------------------------------
try:
    from mcp.client.session import LATEST_HANDSHAKE_VERSION
except ImportError:  # pragma: no cover - pre-2.x
    try:
        from mcp.types import LATEST_PROTOCOL_VERSION as LATEST_HANDSHAKE_VERSION
    except ImportError:  # pragma: no cover - SDK absent
        LATEST_HANDSHAKE_VERSION = None  # type: ignore[assignment]

try:
    from mcp.types import LATEST_PROTOCOL_VERSION
except ImportError:  # pragma: no cover - SDK absent
    LATEST_PROTOCOL_VERSION = None  # type: ignore[assignment]


def sdk_httpx() -> Any:
    """Return the httpx module the installed MCP SDK is built against.

    mcp 2.x moved from ``httpx`` to ``httpx2``; every object crossing the SDK
    boundary must come from the module the SDK itself imports or it fails at
    the transport layer.
    """
    try:
        import mcp.client.streamable_http as _transport

        return getattr(_transport, "httpx2", None) or getattr(_transport, "httpx", None)
    except ImportError:  # pragma: no cover - SDK absent
        return None


__all__ = [
    "ClientSession",
    "StdioServerParameters",
    "stdio_client",
    "streamable_http_client",
    "sse_client",
    "MCPServer",
    "LATEST_HANDSHAKE_VERSION",
    "LATEST_PROTOCOL_VERSION",
    "sdk_httpx",
]
