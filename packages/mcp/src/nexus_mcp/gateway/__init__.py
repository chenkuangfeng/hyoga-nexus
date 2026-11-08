"""Bridge enabled MCP tools into `AuthorizedToolGateway` (openspec 2026-11-08-mcp, R4/R6/R7).

The platform owns data and authorization; this module only projects a resolved, enabled tool into a
`RegisteredTool` whose handler re-validates at call time through an injected executor and then
invokes `nexus_mcp.client.call`. It never grants anything itself.
"""
from __future__ import annotations

from typing import Protocol

from nexus_core.runtime import ToolDefinition, ToolResult
from nexus_tools.registry import RegisteredTool, ToolContext

from nexus_mcp.client.names import external_description, registered_name

#: The model-facing prefix for an external tool's result (R6), kept out of the stored invocation data.
_EXTERNAL_RESULT_PREFIX = "[MCP 工具返回的外部数据]"


class McpToolExecutor(Protocol):
    """Executes one already-authorized MCP tool, re-validating service, whitelist and risk first."""

    async def call(self, service_id: str, tool_name: str, arguments: dict) -> ToolResult: ...


def tool_definition(
    *,
    service_id: str,
    service_name: str,
    tool_name: str,
    description: str,
    input_schema: dict,
    risk: str,
    requires_approval: bool = False,
    timeout_seconds: float = 30.0,
) -> ToolDefinition:
    """Project one visible MCP tool into a provider-safe `ToolDefinition`.

    The name is the collision-resistant registered name; the description carries the external source
    prefix; the schema is stored raw so `nexus_core.schema.restore` can undo provider renames while
    `nexus_core.schema.sanitize` produces the model-visible copy. An empty or missing schema becomes
    the empty-object schema (WeKnora ``MCPTool.Parameters``).
    """
    schema = dict(input_schema) if isinstance(input_schema, dict) and input_schema else {"type": "object", "properties": {}}
    read_only = risk == "read"
    return ToolDefinition(
        name=registered_name(service_id, service_name, tool_name),
        description=external_description(service_name, service_id, tool_name, description or ""),
        parameters=schema,
        source="mcp",
        group="mcp",
        deferrable=True,
        read_only=read_only,
        side_effects=not read_only,
        risk=risk,
        requires_approval=False if read_only else bool(requires_approval),
        timeout_seconds=max(timeout_seconds, 1.0),
    )


def make_registered_tool(
    definition: ToolDefinition,
    *,
    service_id: str,
    tool_name: str,
    executor: McpToolExecutor,
) -> RegisteredTool:
    """Build the registered tool whose handler delegates to `executor` (which revalidates, then calls)."""

    async def handler(arguments: dict, context: ToolContext) -> ToolResult:
        return await executor.call(service_id, tool_name, arguments)

    def public_result(result: ToolResult) -> str:
        if result.error_code:
            return result.data or result.error_code
        data = result.data
        return f"{_EXTERNAL_RESULT_PREFIX}\n{data}" if data else "Tool finished"

    return RegisteredTool(definition, handler, public_result)


def register_tools(registry, definitions: list[ToolDefinition], executor: McpToolExecutor,
                   tool_names: dict[ToolDefinition, tuple[str, str]]) -> None:
    """Register each definition; `tool_names` maps a definition to its (service_id, tool_name).

    Duplicate registered names are rejected by `ToolRegistry` (first-wins is enforced by the caller
    ordering; a re-registration of the same name raises).
    """
    for definition in definitions:
        service_id, tool_name = tool_names[definition]
        registry.register(make_registered_tool(definition, service_id=service_id, tool_name=tool_name, executor=executor))
