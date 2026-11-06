"""Shared HTTP helper for REST vector engines (Qdrant, Elasticsearch, Milvus).

Every engine response error becomes :class:`VectorStoreError` with a stable code, and no request ever
includes secrets in the error text. ``verify_tls`` defaults to True; disabling it is a per-store choice
(WeKnora ``ConnectionConfig.InsecureSkipVerify``).
"""
from __future__ import annotations

from typing import Any, Mapping

import httpx

from .base import VectorStoreError

DEFAULT_TIMEOUT = 30.0


class RestClient:
    def __init__(self, base_url: str, headers: Mapping[str, str] | None = None, *, verify_tls: bool = True,
                 timeout: float = DEFAULT_TIMEOUT, auth: tuple[str, str] | None = None) -> None:
        if not base_url:
            raise VectorStoreError('invalid_config', 'vector store address is required')
        self._client = httpx.AsyncClient(base_url=base_url.rstrip('/'), headers=dict(headers or {}),
                                         verify=verify_tls, timeout=timeout, auth=auth)

    async def request(self, method: str, path: str, json: Any = None, *, allow: tuple[int, ...] = ()) -> Any:
        try:
            response = await self._client.request(method, path, json=json)
        except httpx.HTTPError as exc:
            raise VectorStoreError('connection_failed', f'{method} {path}: {type(exc).__name__}') from exc
        if response.status_code in allow:
            return None
        if response.status_code >= 400:
            raise VectorStoreError(f'http_{response.status_code}', f'{method} {path}: {response.text[:300]}')
        if not response.content:
            return None
        try:
            return response.json()
        except ValueError:
            return response.text

    async def close(self) -> None:
        await self._client.aclose()
