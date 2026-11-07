"""Fetch a public web page for the model, with SSRF protection.

The checks and the download loop live in `nexus_core.egress` (shared with skill installation from a remote source):
every hop (the first request and each redirect) is checked before anything is sent: the scheme and port are
restricted, the host is resolved, and *every* resolved address must be globally routable (loopback, private,
link-local, cloud-metadata and other special ranges are refused). The request then connects to the validated
literal address while TLS still verifies the original host name, so a DNS answer that changes between check
and connect cannot redirect it (octop-harness `security/ssrf.py`, Hermes `url_safety.py`). Redirects are followed
by hand, a few at a time, because the client's own redirect handling would skip the check. The body is read
with a byte limit. Page text is external data: callers mark it as such.
"""
from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser

import httpx

from nexus_core import egress

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


def _translate(exc: egress.EgressError) -> WebError:
    return WebError(exc.code.replace('egress_', 'web_', 1), exc.detail)


default_resolver = egress.default_resolver


def check_url(url: str) -> tuple[str, str, int]:
    """(scheme, host, port) of an acceptable URL, or WebError. Does not touch the network."""
    try:
        return egress.check_url(url, ALLOWED_PORTS)
    except egress.EgressError as exc:
        raise _translate(exc) from None


def _public(address: str) -> bool:
    return egress.is_public(address)


async def validate_destination(host: str, port: int, resolver=default_resolver) -> str:
    """The address to connect to, after checking that every address the host resolves to is public."""
    try:
        return await egress.validate_destination(host, port, resolver)
    except egress.EgressError as exc:
        raise _translate(exc) from None


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
    try:
        got = await egress.download(
            url, max_bytes=max_bytes, timeout=timeout, ports=ALLOWED_PORTS, resolver=resolver, transport=transport,
            max_redirects=MAX_REDIRECTS,
            headers={'User-Agent': 'HyogaNexus-WebFetch/1.0',
                     'Accept': 'text/html,text/plain,application/json;q=0.9,*/*;q=0.1'})
    except egress.EgressError as exc:
        raise _translate(exc) from None
    title, text = extract(got.body, got.headers.get('content-type', ''))
    return Page(got.url, title, text, got.truncated)
