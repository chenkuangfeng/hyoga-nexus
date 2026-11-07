"""Vision model access for `vision_analyze` (openspec 2026-11-07-tool-expansion 8.3).

The model profile is authorized and its key leased for each call through `owner_model_call`, the same path the
knowledge base uses for image descriptions, so a revoked grant stops the tool at the next call.
"""
from __future__ import annotations

from uuid import UUID

from nexus_core.runtime import RuntimeFault

SYSTEM = 'You describe and answer questions about images accurately. Say so when something cannot be seen.'


class VisionAnalyzer:
    """One analysis per call; the client is created and closed around it."""

    def __init__(self, factory, tenant_id: UUID, user_id: UUID, version_id: str, *, client_factory=None):
        self.factory, self.tenant_id, self.user_id, self.version_id = factory, tenant_id, user_id, UUID(version_id)
        self._client_factory = client_factory

    def _client(self):
        if self._client_factory is not None:
            return self._client_factory(self.factory, self.tenant_id, self.user_id, self.version_id, 'chat.vision')
        from .knowledge_index import knowledge_vision
        return knowledge_vision(self.factory, self.tenant_id, self.user_id, self.version_id, 'chat.vision')

    async def analyze(self, image: bytes, mime: str, question: str) -> str:
        try:
            client = self._client()
        except Exception:
            raise RuntimeFault('vision_model_unavailable') from None
        try:
            return await client.describe(image, mime, SYSTEM, question, 1500)
        finally:
            await client.close()
