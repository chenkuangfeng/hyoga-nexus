"""Connection, tool discovery and tool invocation against external MCP servers.

All ``mcp.*`` imports go through `nexus_mcp._sdk`; nothing else in this package touches the SDK.
Discovery always uses a one-shot connection that is torn down afterwards (WeKnora catalogs load
tools once with a bounded budget); stdio calls may reuse a `StdioSessionPool`, because respawning a
subprocess on every call is the dominant cost. The pool's lifetime model is the deer-flow
``session_pool.py`` owner-task pattern: a dedicated task enters and exits each `ClientSession`, so
anyio's cancel-scope ownership is always satisfied.
"""
from __future__ import annotations

import asyncio
import json
import sys
from collections import OrderedDict
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import AsyncIterator

from nexus_core.runtime import ToolResult
from nexus_mcp._sdk import (
    ClientSession,
    MCPError as SdkMcpError,
    StdioServerParameters,
    sdk_httpx,
    sse_client,
    stdio_client,
    streamable_http_client,
)

from .config import assert_resolved, fingerprint, validate_config
from .errors import (
    McpCallRejected,
    McpConnectionError,
    McpDiscoveryTimeout,
    McpError,
    McpOutputSchemaError,
    McpUnauthorized,
    is_unauthorized,
)

DEFAULT_TIMEOUT = 30


@dataclass(frozen=True)
class MCPToolSpec:
    """A discovered external tool: name, model-facing description and schemas.

    `read_only_hint` is the server's own claim (never trusted on its own); the risk policy in
    `nexus_platform.mcp` combines it with observed and explicit risk. Schemas are raw JSON-schema
    dicts and never carry credentials.
    """
    name: str
    description: str
    input_schema: dict
    read_only_hint: bool = False
    output_schema: dict | None = None


def _tool_spec(tool) -> MCPToolSpec:
    annotations = getattr(tool, "annotations", None)
    read_only_hint = bool(getattr(annotations, "read_only_hint", None)) if annotations is not None else False
    input_schema = getattr(tool, "input_schema", None)
    if not isinstance(input_schema, dict) or not input_schema:
        input_schema = {"type": "object", "properties": {}}
    output_schema = getattr(tool, "output_schema", None)
    return MCPToolSpec(
        name=getattr(tool, "name", "") or "",
        description=(getattr(tool, "description", None) or "").strip(),
        input_schema=dict(input_schema),
        read_only_hint=read_only_hint,
        output_schema=dict(output_schema) if isinstance(output_schema, dict) else None,
    )


@asynccontextmanager
async def _stdio_transport(config: dict) -> AsyncIterator[tuple]:
    params = StdioServerParameters(
        command=config["command"],
        args=list(config.get("args") or []),
        env={k: v for k, v in (config.get("env") or {}).items()},
    )
    async with stdio_client(params, errlog=sys.stderr) as streams:
        yield streams


@asynccontextmanager
async def _http_transport(config: dict) -> AsyncIterator[tuple]:
    headers = {k: v for k, v in (config.get("headers") or {}).items()}
    httpx = sdk_httpx()
    client = httpx.AsyncClient(headers=headers, timeout=config["timeout"], follow_redirects=False)
    try:
        async with streamable_http_client(config["url"], http_client=client) as streams:
            yield streams
    finally:
        await client.aclose()


@asynccontextmanager
async def _sse_transport(config: dict) -> AsyncIterator[tuple]:
    headers = {k: v for k, v in (config.get("headers") or {}).items()}
    async with sse_client(
        config["url"],
        headers=headers,
        timeout=config["timeout"],
        sse_read_timeout=config.get("sse_read_timeout", 300),
    ) as streams:
        yield streams


def _transport(config: dict):
    return {"stdio": _stdio_transport, "streamable_http": _http_transport, "sse": _sse_transport}[config["transport"]]


@asynccontextmanager
async def _session(config: dict) -> AsyncIterator[ClientSession]:
    transport = _transport(config)
    async with transport(config) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream, read_timeout_seconds=config.get("timeout")) as session:
            await session.initialize()
            yield session


def _sanitize(reason: BaseException) -> str:
    text = str(reason) or reason.__class__.__name__
    return text.replace("\r", " ").replace("\n", " ")[:300]


async def _discover_once(config: dict) -> list[MCPToolSpec]:
    async with _session(config) as session:
        result = await session.list_tools()
        return [_tool_spec(tool) for tool in (getattr(result, "tools", None) or [])]


async def discover(config: dict, *, timeout: float = DEFAULT_TIMEOUT) -> list[MCPToolSpec]:
    """List a server's tools. HTTP transports retry once after dropping the connection; stdio never retries."""
    config = validate_config(config)
    assert_resolved(config)
    retries = 0 if config["transport"] == "stdio" else 1
    for attempt in range(retries + 1):
        try:
            return await asyncio.wait_for(_discover_once(config), timeout)
        except asyncio.TimeoutError as exc:
            raise McpDiscoveryTimeout(f"工具发现超时（{timeout:.0f}s）", code="mcp_discovery_timeout") from exc
        except McpError:
            raise
        except SdkMcpError as exc:
            if is_unauthorized(exc):
                raise McpUnauthorized("MCP 服务要求 OAuth 授权或令牌已失效", code="mcp_unauthorized") from exc
            raise McpConnectionError(f"MCP 握手被拒绝：{_sanitize(exc)}", code="mcp_connection_failed") from exc
        except Exception as exc:
            if is_unauthorized(exc):
                # Retrying with the same bearer token cannot help; the platform refreshes once.
                raise McpUnauthorized("MCP 服务要求 OAuth 授权或令牌已失效", code="mcp_unauthorized") from exc
            if attempt < retries:
                continue
            raise McpConnectionError(f"MCP 连接失败：{_sanitize(exc)}", code="mcp_connection_failed") from exc
    raise McpConnectionError("MCP 连接失败", code="mcp_connection_failed")


def _join_text(content) -> str:
    parts = []
    for block in content or []:
        if getattr(block, "type", None) == "text":
            parts.append(getattr(block, "text", ""))
    return "".join(parts)


def validate_output(structured: object, output_schema: dict | None) -> str | None:
    """Return a stable error code when structured output breaks the declared schema, else None."""
    if not output_schema or structured is None:
        return None
    from jsonschema import Draft202012Validator
    try:
        Draft202012Validator(output_schema).validate(structured)
        return None
    except Exception:
        return "mcp_output_schema_failed"


async def call(
    config: dict,
    tool_name: str,
    arguments: dict | None,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    output_schema: dict | None = None,
    pool: "StdioSessionPool | None" = None,
) -> ToolResult:
    """Invoke one tool and classify the failure. Never retries; the platform may retry a 401 once.

    `pool` reuses a long-lived stdio session; `output_schema`, when present, validates structured
    output and classifies a mismatch as an output-schema failure (retry with the same arguments).
    """
    config = validate_config(config)
    assert_resolved(config)
    if config["transport"] == "stdio" and pool is not None:
        async with pool.lease(config) as session:
            return await _call_session(session, tool_name, arguments, timeout, output_schema)
    async with _session(config) as session:
        return await _call_session(session, tool_name, arguments, timeout, output_schema)


async def _call_session(session, tool_name, arguments, timeout, output_schema) -> ToolResult:
    try:
        result = await asyncio.wait_for(session.call_tool(tool_name, arguments or {}), timeout)
    except asyncio.TimeoutError as exc:
        raise McpConnectionError("MCP 调用超时", code="mcp_call_timeout") from exc
    except SdkMcpError as exc:
        if is_unauthorized(exc):
            raise McpUnauthorized("MCP 服务要求 OAuth 授权或令牌已失效", code="mcp_unauthorized") from exc
        raise McpCallRejected(
            f"MCP 服务拒绝了调用。请修正参数类型、必填字段与嵌套后重试。（{_sanitize(exc)}）", code="mcp_call_rejected"
        ) from exc
    except McpError:
        raise
    except Exception as exc:
        if is_unauthorized(exc):
            raise McpUnauthorized("MCP 服务要求 OAuth 授权或令牌已失效", code="mcp_unauthorized") from exc
        raise McpConnectionError(f"MCP 调用失败：{_sanitize(exc)}", code="mcp_call_failed") from exc
    if getattr(result, "is_error", False):
        raise McpCallRejected("MCP 服务拒绝了调用。请修正参数类型、必填字段与嵌套后重试。", code="mcp_call_rejected")
    structured = getattr(result, "structured_content", None)
    code = validate_output(structured, output_schema)
    if code:
        raise McpOutputSchemaError("参数已被接受，不要改参数重试。", code=code)
    text = _join_text(getattr(result, "content", None))
    if structured is not None and not text:
        try:
            text = json.dumps(structured, ensure_ascii=False)
        except Exception:
            text = str(structured)
    return ToolResult(text)


class StdioSessionPool:
    """LRU pool of long-lived stdio sessions, one owner task per session (deer-flow pattern).

    A pooled session is entered and exited by the same owner task; acquisition and release only
    bump an active counter, and eviction signals the owner's close event. Sessions are never shared
    across event loops: this pool belongs to one loop.
    """

    def __init__(self, max_size: int = 8, init_timeout: float = DEFAULT_TIMEOUT):
        self.max_size = max_size
        self.init_timeout = init_timeout
        self._entries: OrderedDict[str, "_Owner"] = OrderedDict()
        self._active: dict["_Owner", int] = {}
        self._lock = asyncio.Lock()

    async def _run_owner(self, owner: "_Owner", config: dict) -> None:
        try:
            async with _stdio_transport(config) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream,
                                         read_timeout_seconds=config.get("timeout")) as session:
                    await session.initialize()
                    owner.session = session
                    if not owner.ready.done():
                        owner.ready.set_result(session)
                    await owner.close_evt.wait()
        except asyncio.CancelledError:
            if not owner.ready.done():
                owner.ready.cancel()
            raise
        except BaseException as exc:
            if not owner.ready.done():
                owner.ready.set_exception(exc)

    async def _spawn_locked(self, key: str, config: dict) -> "_Owner":
        owner = _Owner()
        loop = asyncio.get_running_loop()
        owner.ready = loop.create_future()
        owner.close_evt = asyncio.Event()
        owner.task = loop.create_task(self._run_owner(owner, config))
        self._entries[key] = owner
        self._evict_locked()
        return owner

    def _evict_locked(self) -> None:
        while len(self._entries) > self.max_size:
            for key, owner in self._entries.items():
                if self._active.get(owner, 0) == 0:
                    self._entries.pop(key)
                    owner.close_evt.set()
                    return
            # Every session busy: reuse the oldest by evicting it after its calls release.
            return

    @asynccontextmanager
    async def lease(self, config: dict) -> AsyncIterator[ClientSession]:
        key = fingerprint(config)
        async with self._lock:
            owner = self._entries.get(key)
            if owner is not None and owner.session is not None and not owner.task.done():
                self._entries.move_to_end(key)
            else:
                if owner is not None:
                    self._entries.pop(key, None)
                owner = await self._spawn_locked(key, config)
            self._active[owner] = self._active.get(owner, 0) + 1
        try:
            session = await asyncio.wait_for(asyncio.shield(owner.ready), self.init_timeout)
        except BaseException:
            await self._release(key, owner)
            raise
        try:
            yield session
        finally:
            await self._release(key, owner)

    async def _release(self, key: str, owner: "_Owner") -> None:
        async with self._lock:
            remaining = self._active.get(owner, 1) - 1
            if remaining:
                self._active[owner] = remaining
            else:
                self._active.pop(owner, None)
                self._evict_locked()

    async def close(self) -> None:
        async with self._lock:
            entries = list(self._entries.values())
            self._entries.clear()
            for owner in entries:
                owner.close_evt.set()
        for owner in entries:
            if owner.task is not None:
                try:
                    await asyncio.wait_for(asyncio.shield(owner.task), self.init_timeout)
                except (asyncio.TimeoutError, asyncio.CancelledError):
                    owner.task.cancel()


class _Owner:
    __slots__ = ("session", "ready", "close_evt", "task")

    def __init__(self) -> None:
        self.session: ClientSession | None = None
        self.ready: asyncio.Future | None = None
        self.close_evt: asyncio.Event | None = None
        self.task: asyncio.Task | None = None
