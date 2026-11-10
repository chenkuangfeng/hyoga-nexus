"""MCP server exposing one endpoint's read-only tools over streamable HTTP (openspec 2026-11-08-mcp, 2.4).

The server is a thin projection over two injected ports (list definitions, execute a tool); the
platform resolves the endpoint token and supplies the ports, so this package never touches the database.
Every ``tools/list`` returns the endpoint's whitelisted read-only definitions and every ``tools/call``
re-checks the tool is still in the whitelist instead of trusting the earlier list.
"""
from __future__ import annotations

from typing import Awaitable, Callable

from nexus_core.runtime import ToolDefinition, ToolResult
from nexus_mcp._sdk import CallToolResult, MCPServer, TextContent, ToolAnnotations, ToolError, ToolType

ListDefinitions = Callable[[], Awaitable[list[ToolDefinition]]]
ExecuteTool = Callable[[str, dict], Awaitable[ToolResult]]


class EndpointMCPServer(MCPServer):
    """An `MCPServer` whose tools are an endpoint's whitelisted read-only definitions."""

    def __init__(self, list_definitions: ListDefinitions, execute_tool: ExecuteTool, *,
                 name: str = "hyoga-nexus", version: str = "0.1.0"):
        super().__init__(name=name, version=version)
        self._list_definitions = list_definitions
        self._execute_tool = execute_tool

    async def list_tools(self) -> list[ToolType]:
        definitions = await self._list_definitions()
        tools: list[ToolType] = []
        for definition in definitions:
            tools.append(ToolType(
                name=definition.name,
                description=definition.description,
                input_schema=definition.parameters,
                annotations=ToolAnnotations(read_only_hint=definition.read_only),
            ))
        return tools

    async def call_tool(self, name: str, arguments: dict, context=None) -> CallToolResult:
        result = await self._execute_tool(name, arguments or {})
        text = result.data or (result.error_code or "tool finished")
        return CallToolResult(content=[TextContent(type="text", text=text)], is_error=result.error_code is not None)


def streamable_http_app(server: MCPServer, *, stateless: bool = True):
    """A Starlette ASGI app for `server`, stateless by default (each request resolves the token)."""
    return server.streamable_http_app(stateless_http=stateless)


__all__ = ["EndpointMCPServer", "streamable_http_app", "ListDefinitions", "ExecuteTool"]
