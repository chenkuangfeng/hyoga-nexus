"""OpenAI-compatible vision and speech-to-text clients (openspec 2026-11-06-knowledge-base K4.2).

Same transport rules as chat models and embeddings (`network.provider_client`: pinned address, no redirects).
Callers resolve the credential, own the client and must close it.

- :class:`OpenAICompatibleVision` sends one image with a prompt to a vision-capable chat model and returns the
  text of the reply (used for image descriptions and OCR of scanned pages).
- :class:`OpenAICompatibleTranscriber` sends an audio file to ``/audio/transcriptions``.

Written without access to a live provider: unit tests use fake clients, real-provider checks are pending.
"""
from __future__ import annotations

import base64

from openai import AsyncOpenAI

from nexus_core.runtime import RuntimeFault
from .network import provider_client

VISION_PROTOCOLS = ('openai_chat_completions', 'openai_responses')
SPEECH_PROTOCOLS = ('openai_chat_completions', 'openai_responses')
MAX_IMAGE_BYTES = 20 * 1024 * 1024
MAX_AUDIO_BYTES = 25 * 1024 * 1024


class OpenAICompatibleVision:
    def __init__(self, *, model: str, api_key: str, base_url: str, timeout: float = 120,
                 share_connections: bool = False) -> None:
        self._model = model
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=timeout, max_retries=0,
                                   http_client=provider_client(base_url, timeout=timeout,
                                                               share_connections=share_connections))

    async def describe(self, image: bytes, mime: str, system: str, prompt: str, max_tokens: int = 1500) -> str:
        if len(image) > MAX_IMAGE_BYTES:
            raise RuntimeFault('image_too_large')
        url = f'data:{mime};base64,{base64.b64encode(image).decode()}'
        reply = await self._client.chat.completions.create(
            model=self._model, max_tokens=max_tokens,
            messages=[{'role': 'system', 'content': system},
                      {'role': 'user', 'content': [{'type': 'text', 'text': prompt},
                                                   {'type': 'image_url', 'image_url': {'url': url}}]}])
        return (reply.choices[0].message.content or '') if reply.choices else ''

    async def close(self) -> None:
        await self._client.close()


class OpenAICompatibleTranscriber:
    def __init__(self, *, model: str, api_key: str, base_url: str, timeout: float = 600,
                 share_connections: bool = False) -> None:
        self._model = model
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=timeout, max_retries=0,
                                   http_client=provider_client(base_url, timeout=timeout,
                                                               share_connections=share_connections))

    async def transcribe(self, audio: bytes, filename: str, language: str | None = None) -> str:
        if len(audio) > MAX_AUDIO_BYTES:
            raise RuntimeFault('audio_too_large')
        extra = {'language': language} if language else {}
        reply = await self._client.audio.transcriptions.create(model=self._model, file=(filename, audio), **extra)
        return getattr(reply, 'text', '') or ''

    async def close(self) -> None:
        await self._client.close()


def create_vision(*, model: str, api_key: str, options: dict, timeout: float = 120,
                  share_connections: bool = False) -> OpenAICompatibleVision:
    if options.get('protocol') not in VISION_PROTOCOLS:
        raise RuntimeFault('runtime_not_configured')
    return OpenAICompatibleVision(model=model, api_key=api_key, base_url=options.get('base_url', 'https://api.openai.com/v1'),
                                  timeout=timeout, share_connections=share_connections)


def create_transcriber(*, model: str, api_key: str, options: dict, timeout: float = 600,
                       share_connections: bool = False) -> OpenAICompatibleTranscriber:
    if options.get('protocol') not in SPEECH_PROTOCOLS:
        raise RuntimeFault('runtime_not_configured')
    return OpenAICompatibleTranscriber(model=model, api_key=api_key,
                                       base_url=options.get('base_url', 'https://api.openai.com/v1'),
                                       timeout=timeout, share_connections=share_connections)
