"""Chat model access for graph building (injected by the composition root, like embeddings).

``complete(factory, tenant_id, user_id, model_version_id, purpose, system, user_text, max_tokens)`` answers the
model's text. Building uses the knowledge base creator's key (decision 6); a model the creator cannot use makes
the build fail with a clear reason instead of falling back to another key.
"""
from __future__ import annotations

from typing import Any, Awaitable, Callable
from uuid import UUID

Completer = Callable[[Any, UUID, UUID, UUID, str, str, str, int], Awaitable[str]]
_COMPLETER: list[Completer] = []


def set_completer(completer: Completer | None) -> None:
    _COMPLETER[:] = [completer] if completer else []


async def complete(factory, tenant_id: UUID, user_id: UUID, model_version_id: UUID, purpose: str, system: str,
                   user_text: str, max_tokens: int = 2000) -> str:
    if not _COMPLETER:
        raise LookupError('no chat model client is configured')
    return await _COMPLETER[0](factory, tenant_id, user_id, model_version_id, purpose, system, user_text, max_tokens)
