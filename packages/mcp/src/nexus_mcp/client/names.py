"""External tool-name boundary and registration names (WeKnora ``mcp_tool.go`` / ``mcp_exposure.go``).

MCP tool names arrive verbatim from external, potentially compromised servers. A name is only ever
a function identifier: the provider validates bound tools against ``^[A-Za-z0-9_-]+$``, but deferred
(tool_search) tools bypass that bind-time check and live only in the system prompt, where a crafted
name (newlines, markdown, angle brackets) could forge prompt structure. The load boundary therefore
validates every external name against the same safe charset and drops the rest (deer-flow ``tools.py``).
"""
from __future__ import annotations

import hashlib
import json
import re

#: Safe identifier charset shared by the provider, the tool registry and the search catalog.
_VALID_TOOL_NAME = re.compile(r"^[A-Za-z0-9_-]+$")
_MAX_FUNCTION_NAME_LENGTH = 64
_MCP_PREFIX = "mcp_"


def valid_external_tool_name(name: object) -> str | None:
    """Return `name` when it is safe to carry into the registry / catalog, else ``None``."""
    if not isinstance(name, str):
        return None
    return name if _VALID_TOOL_NAME.fullmatch(name) else None


def sanitize_name(name: str) -> str:
    """Lowercase, fold spaces and hyphens to underscores, keep only ``[a-z0-9_]`` (WeKnora)."""
    name = name.lower().replace(" ", "_").replace("-", "_")
    return "".join(ch for ch in name if ("a" <= ch <= "z") or ("0" <= ch <= "9") or ch == "_")


def registered_name(service_id: str, service_name: str, tool_name: str) -> str:
    """The model-visible registered name, independent of enumeration order and schema revisions.

    Hash the raw ``service_id + "\\x00" + tool_name`` so sanitizing Unicode or truncating names
    alone cannot silently alias two distinct tools, while keeping an ASCII hint for readability.
    """
    digest = hashlib.sha256(f"{service_id}\x00{tool_name}".encode()).hexdigest()
    suffix = digest[:16]
    hint = f"{sanitize_name(service_name)}_{sanitize_name(tool_name)}"
    max_hint = _MAX_FUNCTION_NAME_LENGTH - len(_MCP_PREFIX) - 1 - len(suffix)
    if len(hint) > max_hint:
        hint = hint[:max_hint]
    return f"{_MCP_PREFIX}{hint}_{suffix}"


def tool_ref(service_id: str, tool_name: str, input_schema: dict) -> str:
    """A stable reference binding identity + schema shape, used for revalidation and approval scope.

    Hash the unmodified identity plus the serialized input schema so a refreshed schema must be
    described again instead of executing arguments built for an older shape (WeKnora ``mcpToolRef``).
    """
    schema_json = json.dumps(input_schema, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    digest = hashlib.sha256(f"{service_id}\x00{tool_name}\x00{schema_json}".encode()).hexdigest()
    return f"mcpt_{digest}"


def external_description(service_name: str, service_id: str, tool_name: str, description: str) -> str:
    """Prefix that identifies the external service and original tool, lowering indirect prompt injection.

    Matches WeKnora ``MCPRegisteredTool.Description``: ``[MCP service "name", server_id="id",
    tool="tool" (external)] {description}``.
    """
    prefix = f'[MCP service "{service_name}", server_id="{service_id}", tool="{tool_name}" (external)] '
    return prefix + (description if description else tool_name)
