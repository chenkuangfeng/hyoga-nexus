"""Fetch a public web page for the model, with SSRF protection.

Every hop (the first request and each redirect) is checked before anything is sent: the scheme and port are
restricted, the host is resolved, and *every* resolved address must be globally routable (loopback, private,
link-local, cloud-metadata and other special ranges are refused). The request then connects to the validated
literal address while TLS still verifies the original host name, so a DNS answer that changes between check
and connect cannot redirect it (octop-harness `security/ssrf.py`, Hermes `url_safety.py`). Redirects are followed
by hand, a few at a time, because the client's own redirect handling would skip the check. The body is read
with a byte limit. Page text is external data: callers mark it as such.
"""
from __future__ import annotations

import asyncio
import ipaddress
import socket
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

import httpx

ALLOWED_PORTS = (80, 443, 8080, 8443)
MAX_REDIRECTS = 5
_TEXT_TYPES = ('text/', 'application/json', 'application/xml', 'application/xhtml', 'application/javascript')


class WebError(Exception):
    """A refused or failed fetch. `code` is stable; `detail` is safe to show the model."""

    def __init__(self, code: str, detail: str = ''):
        super().__init__(code)
        self.code, self.detail = code, detail


@dataclass(frozen=True)
class Page:
    url: str
    title: str
    text: str
    truncated: bool


async def default_resolver(host: str, port: int) -> list[str]:
    """Addresses of `host`, bounded to five seconds."""
    try:
        results = await asyncio.wait_for(asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM), 5)
    except (OSError, asyncio.TimeoutError):
        raise WebError('web_unreachable', 'the host name could not be resolved') from None
    return [item[4][0] for item in results]


def check_url(url: str) -> tuple[str, str, int]:
    """(scheme, host, port) of an acceptable URL, or WebError. Does not touch the network."""
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError:
        raise WebError('web_url_invalid') from None
    if (parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password
            or any(c.isspace() or ord(c) < 32 for c in url) or len(url) > 2048):
        raise WebError('web_url_invalid', 'only http and https URLs without credentials are allowed')
    port = port or (443 if parsed.scheme == 'https' else 80)
    if port not in ALLOWED_PORTS:
        raise WebError('web_destination_denied', f'port {port} is not allowed')
    return parsed.scheme, parsed.hostname, port


def _public(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address.split('%')[0])
    except ValueError:
        return False
    if ip.version == 6 and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


async def validate_destination(host: str, port: int, resolver=default_resolver) -> str:
    """The address to connect to, after checking that every address the host resolves to is public."""
    try:
        literal = [str(ipaddress.ip_address(host))]
    except ValueError:
        literal = None
    addresses = literal or await resolver(host, port)
    if not addresses or not all(_public(address) for address in addresses):
        raise WebError('web_destination_denied', 'the address is not publicly routable')
    return addresses[0]


class _Text(HTMLParser):
    """Visible text and title of an HTML page; scripts, styles and similar are skipped."""
    _SKIP = {'script', 'style', 'noscript', 'template', 'svg', 'head'}
    _BLOCK = {'p', 'div', 'br', 'li', 'tr', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'section', 'article', 'pre', 'blockquote', 'table'}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title, self._skip, self._in_title = '', 0, False

    def handle_starttag(self, tag, attrs):
        if tag == 'title':
            self._in_title = True
        elif tag in self._SKIP:
            self._skip += 1
        elif tag in self._BLOCK:
            self.parts.append('\n')

    def handle_endtag(self, tag):
        if tag == 'title':
            self._in_title = False
        elif tag in self._SKIP and self._skip:
            self._skip -= 1
        elif tag in self._BLOCK:
            self.parts.append('\n')

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self._skip:
            self.parts.append(data)

    def text(self) -> str:
        lines = (' '.join(line.split()) for line in ''.join(self.parts).splitlines())
        out: list[str] = []
        for line in lines:
            if line or (out and out[-1]):
                out.append(line)
        return '\n'.join(out).strip()


def extract(body: bytes, content_type: str) -> tuple[str, str]:
    """(title, text) of a fetched body. Binary and unknown types are refused."""
    kind, _, params = content_type.partition(';')
    kind = kind.strip().lower()
    if kind and not kind.startswith(_TEXT_TYPES):
        raise WebError('web_unsupported_content_type', f'{kind} cannot be read as text')
    charset = 'utf-8'
    for part in params.split(';'):
        name, _, value = part.strip().partition('=')
        if name.lower() == 'charset' and value:
            charset = value.strip('"\' ')
    try:
        text = body.decode(charset, 'replace')
    except LookupError:
        text = body.decode('utf-8', 'replace')
    if kind in ('text/html', 'application/xhtml+xml', ''):
        parser = _Text()
        parser.feed(text)
        return ' '.join(parser.title.split()), parser.text()
    return '', text.strip()


async def fetch(url: str, *, max_bytes: int, timeout: float, resolver=default_resolver,
                transport: httpx.AsyncBaseTransport | None = None) -> Page:
    """Fetch `url` (following up to five redirects) and return its readable text."""
    async with httpx.AsyncClient(transport=transport or httpx.AsyncHTTPTransport(trust_env=False, retries=0),
                                 follow_redirects=False, trust_env=False, timeout=timeout) as client:
        current = url
        for _ in range(MAX_REDIRECTS + 1):
            scheme, host, port = check_url(current)
            address = await validate_destination(host, port, resolver)
            parsed = urlsplit(current)
            netloc = f'[{address}]' if ':' in address else address
            pinned = parsed._replace(netloc=netloc + (f':{parsed.port}' if parsed.port else '')).geturl()
            request = client.build_request('GET', pinned, headers={
                'Host': parsed.netloc.rpartition('@')[2], 'User-Agent': 'HyogaNexus-WebFetch/1.0',
                'Accept': 'text/html,text/plain,application/json;q=0.9,*/*;q=0.1'},
                extensions={'sni_hostname': host})
            try:
                response = await client.send(request, stream=True)
            except httpx.TimeoutException:
                raise WebError('web_timeout') from None
            except httpx.HTTPError:
                raise WebError('web_unreachable', 'the request failed') from None
            try:
                if response.status_code in (301, 302, 303, 307, 308) and response.headers.get('location'):
                    current = urljoin(current, response.headers['location'])
                    continue
                if response.status_code >= 400:
                    raise WebError('web_http_error', f'the server answered {response.status_code}')
                body, truncated = bytearray(), False
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > max_bytes:
                        del body[max_bytes:]
                        truncated = True
                        break
                title, text = extract(bytes(body), response.headers.get('content-type', ''))
                return Page(current, title, text, truncated)
            finally:
                await response.aclose()
        raise WebError('web_too_many_redirects')
