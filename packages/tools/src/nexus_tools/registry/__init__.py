from __future__ import annotations

import inspect
import re
from dataclasses import dataclass
from typing import Awaitable, Callable

from jsonschema import Draft202012Validator
from nexus_core.runtime import CancellationTokenPort, ToolDefinition, ToolResult


@dataclass(frozen=True)
class ToolContext:
    invocation_id: str
    run_id: str
    session_id: str
    tenant_id: str
    cancellation: CancellationTokenPort
    # Run-scoped services (for builtins: the Run's store). Shared tool definitions reach run state only through here.
    services: object | None = None


@dataclass(frozen=True)
class RegisteredTool:
    definition: ToolDefinition
    handler: Callable[[dict[str, object], ToolContext], object]
    # Author of a tool must explicitly select what is public; default has no raw data.
    public_result: Callable[[ToolResult], str] = lambda result: result.error_code or 'Tool finished'


class ToolRegistry:
    def __init__(self):
        self._tools: dict[tuple[str, str], RegisteredTool] = {}

    def fork(self) -> ToolRegistry:
        """Return a Run-owned registration map without copying stateless handlers.

        Registering an MCP/provider tool must never mutate the process-wide builtin catalog.
        Model-visible schemas are deep-copied by the authorized gateway before exposure.
        """
        result = ToolRegistry()
        result._tools = dict(self._tools)
        return result

    def register(self, tool: RegisteredTool):
        definition = tool.definition
        key = (definition.name, definition.version)
        if not re.fullmatch(r'[a-zA-Z_][a-zA-Z0-9_]{0,63}', definition.name) or key in self._tools:
            raise ValueError('Invalid or duplicate tool definition')
        if not callable(tool.handler):
            raise ValueError('Tool handler must be callable')
        if definition.timeout_seconds <= 0:
            raise ValueError('Tool timeout must be positive')
        Draft202012Validator.check_schema(definition.parameters)
        self._tools[key] = tool

    def definitions(self) -> list:
        """Every registered tool's definition (all versions)."""
        return [tool.definition for tool in self._tools.values()]

    def get(self, name: str, version: str) -> RegisteredTool | None:
        return self._tools.get((name, version))
