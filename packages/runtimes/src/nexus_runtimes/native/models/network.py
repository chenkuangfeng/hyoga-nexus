"""Resolve, validate and pin provider destinations before transmitting credentials."""
from __future__ import annotations

import asyncio
import ipaddress
import os
import socket
from urllib.parse import urlsplit

import httpx
from nexus_core.runtime import RuntimeFault


def validate_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
        allowed = {host.strip().lower() for host in os.getenv('NEXUS_MODEL_PRIVATE_HOST_ALLOWLIST', '').split(',') if host.strip()}
        if (not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment
                or any(c.isspace() or ord(c) < 32 for c in value) or '\\' in value
                or parsed.scheme not in ('https', 'http')
                or (parsed.scheme == 'http' and parsed.hostname.lower() not in allowed)):
            raise ValueError
        if parsed.port is not None and not 1 <= parsed.port <= 65535:
            raise ValueError
        try:
            address = ipaddress.ip_address(parsed.hostname)
        except ValueError:
            address = None
        if address and not address.is_global and parsed.hostname.lower() not in allowed:
            raise ValueError
        return value.rstrip('/')
    except ValueError:
        raise RuntimeFault('model_destination_denied') from None


class PinnedTransport(httpx.AsyncBaseTransport):
    def __init__(self, base_url: str):
        self.url = httpx.URL(validate_url(base_url))
        self.inner = httpx.AsyncHTTPTransport(trust_env=False, retries=0)

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if (request.url.scheme, request.url.host, request.url.port) != (self.url.scheme, self.url.host, self.url.port):
            raise RuntimeFault('model_destination_denied')
        try:
            results = await asyncio.wait_for(asyncio.get_running_loop().getaddrinfo(
                request.url.host, request.url.port or (443 if request.url.scheme == 'https' else 80),
                type=socket.SOCK_STREAM), 5)
        except (OSError, asyncio.TimeoutError):
            raise RuntimeFault('model_provider_unavailable') from None
        allowed = {host.strip().lower() for host in os.getenv('NEXUS_MODEL_PRIVATE_HOST_ALLOWLIST', '').split(',') if host.strip()}
        addresses = [item[4][0] for item in results]
        if not addresses or (request.url.host.lower() not in allowed and
                any(not ipaddress.ip_address(address).is_global for address in addresses)):
            raise RuntimeFault('model_destination_denied')
        hostname = request.url.host
        request.headers['Host'] = request.url.netloc.decode('ascii')
        request.extensions['sni_hostname'] = hostname
        request.url = request.url.copy_with(host=addresses[0])
        # The socket connects to a validated literal IP; TLS still authenticates hostname.
        return await self.inner.handle_async_request(request)

    async def aclose(self) -> None:
        await self.inner.aclose()


def provider_client(base_url: str, *, timeout: float = 60) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=PinnedTransport(base_url), follow_redirects=False,
                             trust_env=False, timeout=timeout)
