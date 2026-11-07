"""Guarded outbound HTTP downloads (shared by `web_fetch` and skill installation from a remote source).

Every hop (the first request and each redirect) is checked before anything is sent: the scheme and port are
restricted, the host is resolved, and *every* resolved address must be globally routable (loopback, private,
link-local, cloud-metadata and other special ranges are refused). The request then connects to the validated
literal address while TLS still verifies the original host name, so a DNS answer that changes between check and
connect cannot redirect it (octop-harness `security/ssrf.py`, Hermes `url_safety.py`). Redirects are followed by
hand, a few at a time, because the client's own redirect handling would skip the check. The body is read with a
byte limit and is never decoded here.

Errors are :class:`EgressError` with stable ``egress_*`` codes; callers translate them into their own error type.
"""
from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

import httpx

DEFAULT_PORTS = (80, 443, 8080, 8443)
MAX_REDIRECTS = 5

Resolver = Callable[[str, int], Awaitable[list[str]]]


class EgressError(Exception):
    """A refused or failed download. `code` is stable; `detail` is safe to show the caller."""

    def __init__(self, code: str, detail: str = ''):
        super().__init__(code)
        self.code, self.detail = code, detail


@dataclass(frozen=True)
class Download:
    """The result: the final URL after redirects, the status and headers, the body and whether it was cut at the limit."""
    url: str
    status: int
    headers: Mapping[str, str]
    body: bytes
    truncated: bool


async def default_resolver(host: str, port: int) -> list[str]:
    """Addresses of `host`, bounded to five seconds."""
    try:
        results = await asyncio.wait_for(asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM), 5)
    except (OSError, asyncio.TimeoutError):
        raise EgressError('egress_unreachable', 'the host name could not be resolved') from None
    return [item[4][0] for item in results]


def check_url(url: str, ports: tuple[int, ...] = DEFAULT_PORTS) -> tuple[str, str, int]:
    """(scheme, host, port) of an acceptable URL, or EgressError. Does not touch the network."""
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError:
        raise EgressError('egress_url_invalid') from None
    if (parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password
            or any(c.isspace() or ord(c) < 32 for c in url) or len(url) > 2048):
        raise EgressError('egress_url_invalid', 'only http and https URLs without credentials are allowed')
    port = port or (443 if parsed.scheme == 'https' else 80)
    if port not in ports:
        raise EgressError('egress_destination_denied', f'port {port} is not allowed')
    return parsed.scheme, parsed.hostname, port


def is_public(address: str) -> bool:
    """Whether an address is globally routable (IPv4-mapped IPv6 is judged by its IPv4 part)."""
    try:
        ip = ipaddress.ip_address(address.split('%')[0])
    except ValueError:
        return False
    if ip.version == 6 and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


async def validate_destination(host: str, port: int, resolver: Resolver = default_resolver) -> str:
    """The address to connect to, after checking that every address the host resolves to is public."""
    try:
        literal = [str(ipaddress.ip_address(host))]
    except ValueError:
        literal = None
    addresses = literal or await resolver(host, port)
    if not addresses or not all(is_public(address) for address in addresses):
        raise EgressError('egress_destination_denied', 'the address is not publicly routable')
    return addresses[0]


async def download(url: str, *, max_bytes: int, timeout: float, headers: Mapping[str, str] | None = None,
                   ports: tuple[int, ...] = DEFAULT_PORTS, resolver: Resolver = default_resolver,
                   transport: httpx.AsyncBaseTransport | None = None, on_oversize: str = 'truncate',
                   max_redirects: int = MAX_REDIRECTS) -> Download:
    """GET `url`, following redirects by hand with every hop checked.

    `on_oversize` is ``truncate`` (return the first `max_bytes`, ``truncated=True``) or ``error`` (raise
    ``egress_too_large`` as soon as the limit is crossed). A status of 400 or more raises ``egress_http_error``.
    """
    async with httpx.AsyncClient(transport=transport or httpx.AsyncHTTPTransport(trust_env=False, retries=0),
                                 follow_redirects=False, trust_env=False, timeout=timeout) as client:
        current = url
        for _ in range(max_redirects + 1):
            _, host, port = check_url(current, ports)
            address = await validate_destination(host, port, resolver)
            parsed = urlsplit(current)
            netloc = f'[{address}]' if ':' in address else address
            pinned = parsed._replace(netloc=netloc + (f':{parsed.port}' if parsed.port else '')).geturl()
            request = client.build_request('GET', pinned, headers={'Host': parsed.netloc.rpartition('@')[2],
                                                                   **(headers or {})},
                                           extensions={'sni_hostname': host})
            try:
                response = await client.send(request, stream=True)
            except httpx.TimeoutException:
                raise EgressError('egress_timeout') from None
            except httpx.HTTPError:
                raise EgressError('egress_unreachable', 'the request failed') from None
            try:
                if response.status_code in (301, 302, 303, 307, 308) and response.headers.get('location'):
                    current = urljoin(current, response.headers['location'])
                    continue
                if response.status_code >= 400:
                    raise EgressError('egress_http_error', f'the server answered {response.status_code}')
                body, truncated = bytearray(), False
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > max_bytes:
                        if on_oversize == 'error':
                            raise EgressError('egress_too_large', f'the response is larger than {max_bytes} bytes')
                        del body[max_bytes:]
                        truncated = True
                        break
                return Download(current, response.status_code, dict(response.headers), bytes(body), truncated)
            finally:
                await response.aclose()
        raise EgressError('egress_too_many_redirects')
