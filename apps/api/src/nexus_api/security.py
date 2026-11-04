"""Refuse development-mode requests that do not arrive on a loopback address (proposal 2026-11-04-skill-scripts, 1.4).

``[auth] mode = "development"`` trusts every caller as one fixed user, so it must never be reachable from
another machine. The check uses the address the connection arrived on (``scope["server"]``), which is
the interface uvicorn accepted the connection on, not a setting that someone has to keep in step with the
start command. A reverse proxy on the same host still connects from loopback; running development mode
behind a proxy is therefore unsupported and is not detected here.
"""
from __future__ import annotations

import ipaddress
from typing import Any

from fastapi.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from nexus_platform.configuration import DatabaseConfigurationError, auth_settings


def is_loopback(host: str | None) -> bool:
    """True for ``localhost`` and loopback IP addresses (127.0.0.0/8, ::1, IPv4-mapped loopback)."""
    if not host:
        return False
    if host.casefold() == "localhost":
        return True
    try:
        address = ipaddress.ip_address(host.split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    return address.is_loopback


def _development_mode() -> bool:
    try:
        return (auth_settings().mode or "").casefold() == "development"
    except DatabaseConfigurationError:
        # The API's own dependency reports this as 503; the guard only restricts the known development case.
        return False


class DevelopmentLoopbackGuard:
    """ASGI middleware: in development mode, answer 403 to any HTTP request that did not arrive on loopback."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and _development_mode():
            server: Any = scope.get("server")
            host = server[0] if server else None
            if not is_loopback(host):
                response = JSONResponse(status_code=403, content={"error": {
                    "code": "forbidden",
                    "message": "Development authentication accepts loopback connections only",
                    "request_id": None}})
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)
