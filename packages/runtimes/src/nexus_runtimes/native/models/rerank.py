"""Rerank model clients (port of WeKnora ``internal/models/api`` rerank protocols; openspec K5.3b).

Three wire shapes cover the common providers; the model's ``rerank_api`` option picks one (default ``cohere``):

- ``cohere``: ``POST {base}/rerank`` ``{model, query, documents, top_n}`` → ``results[{index, relevance_score}]``
  (Cohere, Jina, Zhipu, SiliconFlow, vLLM, Xinference...);
- ``tei``: ``POST {base}/rerank`` ``{query, texts}`` → ``[{index, score}]`` (Hugging Face Text Embeddings
  Inference);
- ``dashscope``: ``POST {base}/services/rerank/text-rerank/text-rerank`` ``{model, input:{query, documents},
  parameters:{top_n, return_documents:false}}`` → ``output.results[{index, relevance_score}]``.

Same pinned, redirect-free transport as chat models. Documents are sent in batches of :data:`BATCH`; scores are
returned per input position. Written without a live provider (unit tests use a mock transport).
"""
from __future__ import annotations

from typing import Sequence

import httpx

from nexus_core.runtime import RuntimeFault
from .network import provider_client

BATCH = 64
APIS = ('cohere', 'tei', 'dashscope')


class RerankError(RuntimeError):
    pass


class HttpReranker:
    def __init__(self, *, model: str, api_key: str, base_url: str, api: str = 'cohere', timeout: float = 60,
                 share_connections: bool = False) -> None:
        if api not in APIS:
            raise RuntimeFault('runtime_not_configured')
        self._model, self._api, self._base = model, api, base_url.rstrip('/')
        self._headers = {'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'}
        self._client: httpx.AsyncClient = provider_client(base_url, timeout=timeout, share_connections=share_connections)

    def _request(self, query: str, documents: Sequence[str]) -> tuple[str, dict]:
        if self._api == 'tei':
            return '/rerank', {'query': query, 'texts': list(documents)}
        if self._api == 'dashscope':
            return '/services/rerank/text-rerank/text-rerank', {
                'model': self._model, 'input': {'query': query, 'documents': list(documents)},
                'parameters': {'top_n': len(documents), 'return_documents': False}}
        return '/rerank', {'model': self._model, 'query': query, 'documents': list(documents), 'top_n': len(documents)}

    @staticmethod
    def _items(api: str, body) -> list[dict]:
        if api == 'tei':
            return body if isinstance(body, list) else []
        if api == 'dashscope':
            return ((body or {}).get('output') or {}).get('results') or []
        return (body or {}).get('results') or (body or {}).get('data') or []

    async def rerank(self, query: str, documents: Sequence[str]) -> list[tuple[int, float]]:
        """``(index, score)`` for every document, indices relative to ``documents``."""
        out: list[tuple[int, float]] = []
        for start in range(0, len(documents), BATCH):
            batch = documents[start:start + BATCH]
            path, payload = self._request(query, batch)
            try:
                response = await self._client.post(self._base + path, headers=self._headers, json=payload)
            except httpx.HTTPError as exc:
                raise RerankError(f'rerank request failed: {type(exc).__name__}') from exc
            if response.status_code >= 400:
                raise RerankError(f'rerank HTTP {response.status_code}: {response.text[:200]}')
            for item in self._items(self._api, response.json()):
                index = item.get('index')
                score = item.get('relevance_score', item.get('score'))
                if not isinstance(index, int) or not isinstance(score, (int, float)) or not 0 <= index < len(batch):
                    raise RerankError('rerank response has an invalid item')
                out.append((start + index, float(score)))
        return out

    async def close(self) -> None:
        await self._client.aclose()


def create_reranker(*, model: str, api_key: str, options: dict, timeout: float = 60,
                    share_connections: bool = False) -> HttpReranker:
    if not options.get('base_url'):
        raise RuntimeFault('runtime_not_configured')
    return HttpReranker(model=model, api_key=api_key, base_url=options['base_url'],
                        api=str(options.get('rerank_api') or 'cohere'), timeout=timeout,
                        share_connections=share_connections)
