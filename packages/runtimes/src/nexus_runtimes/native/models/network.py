"""Resolve, validate and pin provider destinations before transmitting credentials."""
from __future__ import annotations

import asyncio
import ipaddress
import socket
import threading
from urllib.parse import urlsplit

import httpx
from nexus_core.deployment import DeploymentConfigError, section
from nexus_core.runtime import RuntimeFault


def private_host_allowlist() -> set[str]:
    """Hostnames allowed to use http or private addresses, from ``[model_network].private_host_allowlist``.

    Absent means none. A malformed value raises RuntimeFault so that model calls fail closed.
    Hostnames are lower-cased so that comparisons match the URL host.
    """
    try:
        values = section("model_network").get("private_host_allowlist", [])
    except DeploymentConfigError:
        raise RuntimeFault('model_destination_denied') from None
    if not isinstance(values, list) or not all(isinstance(item, str) for item in values):
        raise RuntimeFault('model_destination_denied')
    return {item.strip().lower() for item in values if item.strip()}


def validate_url(value: str) -> str:
    """Normalize a provider base URL or raise the stable destination-denied RuntimeFault.

    Saving a valid URL does not establish DNS safety: the transport checks and pins addresses
    for every request. Private HTTP destinations require deployment-level hostname allowlisting.
    """
    try:
        parsed = urlsplit(value)
        allowed = private_host_allowlist()
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
    """HTTPX transport restricted to one provider origin and validated numeric addresses.

    DNS resolution is bounded to five seconds. Host and TLS SNI retain the original hostname,
    while the connection uses a literal approved IP. No ambient proxy or redirect can redirect
    credential transmission. The owner must close this transport with its HTTP client.

    ``inner`` may be a connection pool shared across Runs (see ``shared_connection_pool``). The
    address check above still runs on every request, and closing this transport never closes a
    pool it did not create.
    """
    def __init__(self, base_url: str, *, inner: httpx.AsyncBaseTransport | None = None):
        self.url = httpx.URL(validate_url(base_url))
        self.inner = inner if inner is not None else httpx.AsyncHTTPTransport(trust_env=False, retries=0)
        self._owns_inner = inner is None

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if (request.url.scheme, request.url.host, request.url.port) != (self.url.scheme, self.url.host, self.url.port):
            raise RuntimeFault('model_destination_denied')
        try:
            results = await asyncio.wait_for(asyncio.get_running_loop().getaddrinfo(
                request.url.host, request.url.port or (443 if request.url.scheme == 'https' else 80),
                type=socket.SOCK_STREAM), 5)
        except (OSError, asyncio.TimeoutError):
            raise RuntimeFault('model_provider_unavailable') from None
        allowed = private_host_allowlist()
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
        if self._owns_inner:
            await self.inner.aclose()


#: One connection pool per provider origin, shared by every Run in the worker process.
#: An httpx pool is bound to the event loop that created it, so each pool records its loop and is
#: used only from that loop. Pools for other loops are never returned, and callers get a private
#: transport instead.
_POOLS: dict[tuple[str, str, int], tuple[httpx.AsyncHTTPTransport, asyncio.AbstractEventLoop]] = {}
_POOLS_LOCK = threading.Lock()
#: Limits applied when a pool for an origin is first created. httpx's own defaults until configured.
_POOL_LIMITS = httpx.Limits(max_connections=100, max_keepalive_connections=20, keepalive_expiry=5.0)


def configure_connection_pool(*, max_connections: int, max_keepalive_connections: int, keepalive_expiry: float) -> None:
    """Set the limits for pools created from now on. Call once at worker start, before any Run.

    Pools that already exist keep their limits until the process restarts.
    """
    global _POOL_LIMITS
    _POOL_LIMITS = httpx.Limits(max_connections=max_connections,
                                max_keepalive_connections=max_keepalive_connections,
                                keepalive_expiry=keepalive_expiry)


def shared_connection_pool(base_url: str) -> httpx.AsyncHTTPTransport | None:
    """Return the process-wide pool for this origin, or None when the caller must not share.

    Returns None when there is no running loop, or when the origin's pool belongs to another loop.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return None
    url = httpx.URL(validate_url(base_url))
    key = (url.scheme, url.host, url.port or (443 if url.scheme == 'https' else 80))
    with _POOLS_LOCK:
        entry = _POOLS.get(key)
        if entry is None:
            entry = (httpx.AsyncHTTPTransport(trust_env=False, retries=0, limits=_POOL_LIMITS), loop)
            _POOLS[key] = entry
        pool, owner = entry
    return pool if owner is loop else None


def provider_client(base_url: str, *, timeout: float = 60, share_connections: bool = False) -> httpx.AsyncClient:
    """Build the controlled async client for connection tests and Native calls.

    With ``share_connections`` the TCP/TLS connections come from the process-wide pool for this
    origin. The per-request address check and redirect rules are unchanged, and credentials are
    never stored in the pool.
    """
    inner = shared_connection_pool(base_url) if share_connections else None
    return httpx.AsyncClient(transport=PinnedTransport(base_url, inner=inner), follow_redirects=False,
                             trust_env=False, timeout=timeout)
