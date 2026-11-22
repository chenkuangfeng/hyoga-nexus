"""OpenAI-compatible embeddings client (openspec 2026-11-06-memory-evolution stage 5, D2).

Uses the same pinned, redirect-free transport as chat models (`network.provider_client`), so a saved
provider URL is checked on every request exactly like a model call. Callers own credential resolution
and must close the client.
"""
from __future__ import annotations

from typing import Sequence

from openai import APIConnectionError, APIError, APIStatusError, APITimeoutError, AsyncOpenAI

from nexus_core.runtime import RuntimeFault
from .errors import ERROR_BODY_LIMIT, bound_error_response, failure
from .network import provider_client

#: Protocols whose providers expose `/embeddings`.
EMBEDDING_PROTOCOLS = ('openai_chat_completions', 'openai_responses')
#: Texts sent in one request.
BATCH = 16


class OpenAICompatibleEmbedder:
    """`embed(texts)` returns one vector per text, in order."""

    def __init__(self, *, model: str, api_key: str, base_url: str, timeout: float = 30,
                 share_connections: bool = False) -> None:
        self._model = model
        client = provider_client(base_url, timeout=timeout, share_connections=share_connections)
        client.event_hooks['response'].append(bound_error_response)
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=timeout, max_retries=0,
                                   http_client=client)

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for start in range(0, len(texts), BATCH):
            try:
                reply = await self._client.embeddings.create(model=self._model, input=list(texts[start:start + BATCH]))
            except APITimeoutError:
                raise RuntimeFault('model_timeout') from None
            except APIConnectionError:
                raise RuntimeFault('model_provider_unavailable') from None
            except APIStatusError as exc:
                body = exc.body if len(exc.response.content) <= ERROR_BODY_LIMIT else None
                raise failure(body, status=exc.status_code, headers=exc.response.headers) from None
            except APIError as exc:
                raise failure(exc.body) from None
            out.extend(list(item.embedding) for item in sorted(reply.data, key=lambda item: item.index))
        return out

    async def close(self) -> None:
        await self._client.close()


def create_embedder(*, model: str, api_key: str, options: dict, timeout: float = 30,
                    share_connections: bool = False) -> OpenAICompatibleEmbedder:
    """Build an embedder for an embedding model version, or refuse an unsupported protocol."""
    if options.get('protocol') not in EMBEDDING_PROTOCOLS:
        raise RuntimeFault('runtime_not_configured')
    return OpenAICompatibleEmbedder(model=model, api_key=api_key, base_url=options.get('base_url', 'https://api.openai.com/v1'),
                                    timeout=timeout, share_connections=share_connections)
