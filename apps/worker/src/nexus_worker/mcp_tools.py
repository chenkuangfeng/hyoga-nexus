"""Register enabled MCP tools into a Run's tool gateway (openspec 2026-11-08-mcp, 1.6).

Definitions are advertised once per Run from live service/tool/policy state; every call re-validates
through ``nexus_platform.mcp.service.resolve_call`` before touching the external server, so a disable or
revocation takes effect on the next call rather than the next Run (WeKnora ``checkEnabled`` recheck).
"""
from __future__ import annotations

from uuid import UUID

from nexus_core.runtime import ToolResult
from nexus_mcp import client as mcp_client
from nexus_mcp import gateway as mcp_gateway
from nexus_mcp.client.errors import McpError, McpUnauthorized
from nexus_platform.errors import PlatformError
from nexus_platform.mcp import service as mcp_service


class McpToolExecutor:
    """Recheck then invoke one MCP tool. Failures become failed `ToolResult`s with stable codes.

    The gateway's own argument guard, risk decision, approval and injection scan still run before this
    executor is reached; here the executor re-validates the live service/tool state and calls the
    external server, translating transport failures into model-safe error results (octop-harness
    ``mcp_tool_error.py``). A 401 triggers exactly one token refresh and one retry; every later
    failure is reported as-is.
    """

    def __init__(self, run_db, factory, tenant_id, principal_id):
        self._run_db = run_db
        self._factory = factory
        self._tenant_id = tenant_id
        self._principal_id = principal_id

    def _resolve(self, service_id: str, tool_name: str, *, force_oauth_refresh: bool = False):
        def read():
            with self._factory() as db:
                with db.begin():
                    return mcp_service.resolve_call(
                        db, self._tenant_id, UUID(service_id), tool_name,
                        principal_id=self._principal_id,
                        force_oauth_refresh=force_oauth_refresh)
        return read

    async def call(self, service_id: str, tool_name: str, arguments: dict) -> ToolResult:
        try:
            resolved, output_schema, timeout = await self._run_db(
                self._resolve(service_id, tool_name))
        except PlatformError as exc:
            return ToolResult(str(exc), error_code=exc.code)
        try:
            return await mcp_client.call(
                resolved, tool_name, arguments, timeout=timeout, output_schema=output_schema
            )
        except McpUnauthorized:
            # Exactly one refresh + retry: the resource server rejected the presented token even
            # though it had not locally expired (revocation, rotation by another process, clock).
            try:
                resolved, output_schema, timeout = await self._run_db(
                    self._resolve(service_id, tool_name, force_oauth_refresh=True))
            except PlatformError as exc:
                return ToolResult(str(exc), error_code=exc.code)
            try:
                return await mcp_client.call(
                    resolved, tool_name, arguments, timeout=timeout, output_schema=output_schema
                )
            except McpError as exc:
                return ToolResult(str(exc), error_code=exc.code)
            except Exception:  # noqa: BLE001
                return ToolResult("MCP 调用失败", error_code="mcp_call_failed")
        except McpError as exc:
            return ToolResult(str(exc), error_code=exc.code)
        except Exception:  # noqa: BLE001 - never leak transport details into the model context
            return ToolResult("MCP 调用失败", error_code="mcp_call_failed")


async def register_mcp_tools(run_db, factory, registry, bound, *, tenant_id, principal_id, service_ids):
    """Add this Run's enabled MCP tools to `registry` and `bound` (both mutated in place).

    Called once per Run before the orchestrator starts; the definitions are the live projection of
    bound services, enabled tools and effective risk. The handler re-validates on every call and
    uses the Run principal's OAuth token where the service requires one.
    """

    def _visible():
        with factory() as db:
            return mcp_service.visible_tools(db, tenant_id, service_ids)

    visible = await run_db(_visible)
    if not visible:
        return
    executor = McpToolExecutor(run_db, factory, tenant_id, principal_id)
    for tool in visible:
        definition = mcp_gateway.tool_definition(
            service_id=str(tool.service_id),
            service_name=tool.service_name,
            tool_name=tool.tool_name,
            description=tool.description,
            input_schema=tool.input_schema,
            risk=tool.risk,
            requires_approval=tool.requires_approval,
            timeout_seconds=tool.timeout,
        )
        registered = mcp_gateway.make_registered_tool(
            definition, service_id=str(tool.service_id), tool_name=tool.tool_name, executor=executor
        )
        registry.register(registered)
        bound[definition.name] = definition.version
