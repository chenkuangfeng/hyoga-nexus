"""Pluggable web search backends (octop-harness `builtin/tools/web_search/_registry.py` is the model).

A backend turns a query into a list of hits. The registry maps the `[web].search_backend` name to a factory,
so adding a provider is one function and one entry. Request shapes follow each provider's public REST API and
have not been exercised against the live services here; the unit tests use a mock transport.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable

import httpx

from .fetch import WebError
from .settings import WebSettings


@dataclass(frozen=True)
class Hit:
    title: str
    url: str
    snippet: str


Backend = Callable[[httpx.AsyncClient, WebSettings, str, int], Awaitable[list[Hit]]]


def _hits(rows, title: str, url: str, snippet: str) -> list[Hit]:
    return [Hit(str(r.get(title) or '')[:200], str(r.get(url) or ''), str(r.get(snippet) or '')[:500])
            for r in rows if isinstance(r, dict) and r.get(url)]


async def _tavily(client, settings, query, limit):
    response = await client.post('https://api.tavily.com/search', json={'query': query, 'max_results': limit},
                                 headers={'Authorization': f'Bearer {settings.search_api_key}'})
    return _hits(_json(response).get('results', []), 'title', 'url', 'content')


async def _brave(client, settings, query, limit):
    response = await client.get('https://api.search.brave.com/res/v1/web/search', params={'q': query, 'count': limit},
                                headers={'X-Subscription-Token': settings.search_api_key, 'Accept': 'application/json'})
    return _hits(_json(response).get('web', {}).get('results', []), 'title', 'url', 'description')


async def _searxng(client, settings, query, limit):
    response = await client.get(settings.search_url.rstrip('/') + '/search', params={'q': query, 'format': 'json'})
    return _hits(_json(response).get('results', [])[:limit], 'title', 'url', 'content')


def _json(response: httpx.Response) -> dict:
    if response.status_code in (401, 403):
        raise WebError('web_search_unauthorized', 'the search service rejected the configured credentials')
    if response.status_code >= 400:
        raise WebError('web_search_failed', f'the search service answered {response.status_code}')
    try:
        value = response.json()
    except ValueError:
        raise WebError('web_search_failed', 'the search service returned an unreadable answer') from None
    return value if isinstance(value, dict) else {}


BACKENDS: dict[str, Backend] = {'tavily': _tavily, 'brave': _brave, 'searxng': _searxng}


async def search(settings: WebSettings, query: str, limit: int, *, transport: httpx.AsyncBaseTransport | None = None) -> list[Hit]:
    """Run `query` on the configured backend. The backend hosts are fixed or operator-set, so no SSRF check applies."""
    backend = BACKENDS.get(settings.search_backend)
    if backend is None:
        raise WebError('web_search_backend_missing', 'no search backend is configured on this server')
    async with httpx.AsyncClient(transport=transport, trust_env=False, timeout=settings.timeout_seconds,
                                 follow_redirects=False) as client:
        try:
            return (await backend(client, settings, query, limit))[:limit]
        except httpx.TimeoutException:
            raise WebError('web_timeout') from None
        except httpx.HTTPError:
            raise WebError('web_search_failed', 'the search service could not be reached') from None
