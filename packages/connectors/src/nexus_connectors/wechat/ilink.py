"""WeChat iLink Bot client: QR binding, long-poll receiving and text replies (openspec 2026-11-11 E4).

Ported from octop-gateway ``channels/weixin`` (``api.py``, ``login_qr.py``) and checked against WeKnora
``internal/im/wechat``; the official terms and token lifetime were not verified here (design 7.4).

- Binding: ``GET ilink/bot/get_bot_qrcode?bot_type=3`` yields ``qrcode`` (polling token) and
  ``qrcode_img_content`` (what to show); ``GET ilink/bot/get_qrcode_status?qrcode=`` reports ``wait``, ``scaned``,
  ``confirmed`` (with ``bot_token``, ``ilink_bot_id``, ``ilink_user_id``, ``baseurl``) or ``expired``.
- Receiving: ``POST ilink/bot/getupdates`` long-polls with the ``get_updates_buf`` cursor.
- Sending: ``POST ilink/bot/sendmessage`` with the ``context_token`` of the message being answered.

Requests use ``AuthorizationType: ilink_bot_token``, ``Authorization: Bearer <token>`` and a random
``X-WECHAT-UIN``; without them the long-poll session never binds (octop-gateway notes).
"""
from __future__ import annotations

import base64
import json
import random
import struct
import uuid
from typing import Any

import httpx

BASE_URL = 'https://ilinkai.weixin.qq.com'
ALLOWED_HOSTS = frozenset({'ilinkai.weixin.qq.com'})
CHANNEL_VERSION = '2.2.0'
CLIENT_VERSION = str((2 << 16) | (2 << 8) | 0)
POLL_TIMEOUT_MS = 35000


class ILinkError(Exception):
    """``retry`` is True for network problems, False when iLink refused (for example an expired token)."""

    def __init__(self, message: str, *, retry: bool, expired: bool = False) -> None:
        super().__init__(message)
        self.retry, self.expired = retry, expired


def _base(url: str | None) -> str:
    """Only the iLink host is accepted, whatever ``baseurl`` the login reports."""
    url = (url or BASE_URL).rstrip('/')
    host = httpx.URL(url).host
    if host not in ALLOWED_HOSTS or not url.startswith('https://'):
        return BASE_URL
    return url


class ILinkLogin:
    def __init__(self, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport

    async def fetch_qr(self) -> dict[str, str]:
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=15.0, transport=self._transport) as client:
            try:
                data = (await client.get('/ilink/bot/get_bot_qrcode', params={'bot_type': '3'},
                                         headers={'iLink-App-ClientVersion': '1'})).json()
            except (httpx.HTTPError, ValueError) as exc:
                raise ILinkError('iLink QR request failed', retry=True) from exc
        if not data.get('qrcode'):
            raise ILinkError('iLink returned no QR code', retry=False)
        return {'qrcode': str(data['qrcode']), 'qrcode_url': str(data.get('qrcode_img_content') or '')}

    async def status(self, qrcode: str) -> dict[str, Any]:
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=40.0, transport=self._transport) as client:
            try:
                data = (await client.get('/ilink/bot/get_qrcode_status', params={'qrcode': qrcode},
                                         headers={'iLink-App-ClientVersion': '1'})).json()
            except (httpx.HTTPError, ValueError) as exc:
                raise ILinkError('iLink QR status failed', retry=True) from exc
        return {'status': str(data.get('status') or 'wait'), 'bot_token': data.get('bot_token'),
                'ilink_bot_id': data.get('ilink_bot_id'), 'ilink_user_id': data.get('ilink_user_id'),
                'baseurl': _base(data.get('baseurl'))}


class ILinkClient:
    def __init__(self, token: str, base_url: str | None = None, *,
                 transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.token, self.base_url, self._transport = token, _base(base_url), transport

    def _headers(self) -> dict[str, str]:
        return {'Content-Type': 'application/json', 'AuthorizationType': 'ilink_bot_token',
                'Authorization': f'Bearer {self.token}',
                'X-WECHAT-UIN': base64.b64encode(struct.pack('>I', random.getrandbits(32))).decode('ascii'),
                'iLink-App-Id': 'bot', 'iLink-App-ClientVersion': CLIENT_VERSION}

    async def _post(self, endpoint: str, data: dict[str, Any], timeout: float) -> dict[str, Any]:
        async with httpx.AsyncClient(base_url=self.base_url, timeout=timeout, transport=self._transport) as client:
            try:
                response = await client.post(f'/{endpoint}', headers=self._headers(),
                                             content=json.dumps(data, ensure_ascii=False, separators=(',', ':')))
                body = response.json()
            except (httpx.HTTPError, ValueError) as exc:
                raise ILinkError(f'iLink {endpoint} failed', retry=True) from exc
        code = body.get('errcode') or body.get('ret') or 0
        if code not in (0, None):
            # -14 is iLink's session timeout: the token no longer works and the owner must scan again.
            raise ILinkError(f'iLink {endpoint} refused ({code})', retry=False, expired=code == -14)
        return body

    async def get_updates(self, cursor: str) -> tuple[list[dict[str, Any]], str]:
        """New messages as ``{'id', 'from', 'text', 'context_token'}`` and the next cursor. Only text is kept."""
        body = await self._post('ilink/bot/getupdates', {
            'get_updates_buf': cursor or '', 'longpolling_timeout_ms': POLL_TIMEOUT_MS,
            'base_info': {'channel_version': CHANNEL_VERSION}}, timeout=POLL_TIMEOUT_MS / 1000 + 5)
        messages = []
        for item in body.get('msgs') or []:
            texts = [part.get('text_item', part.get('textItem', {})).get('text', '')
                     for part in item.get('item_list') or item.get('itemList') or [] if part.get('type') == 1]
            sender = item.get('from_user_id') or item.get('fromUserId')
            message_type = item.get('message_type', item.get('messageType'))
            if sender and message_type != 2 and any(texts):  # 2 is the bot's own message
                messages.append({'id': str(item.get('message_id') or item.get('messageId') or item.get('seq') or ''),
                                 'from': str(sender), 'text': '\n'.join(text for text in texts if text),
                                 'context_token': item.get('context_token') or item.get('contextToken') or ''})
        return messages, str(body.get('get_updates_buf') or body.get('getUpdatesBuf') or cursor or '')

    async def send_text(self, to_user_id: str, text: str, context_token: str = '') -> None:
        await self._post('ilink/bot/sendmessage', {
            'msg': {'from_user_id': '', 'to_user_id': to_user_id, 'client_id': f'nexus-{uuid.uuid4().hex}',
                    'message_type': 2, 'message_state': 2, 'context_token': context_token or None,
                    'item_list': [{'type': 1, 'text_item': {'text': text}}]},
            'base_info': {'channel_version': CHANNEL_VERSION}}, timeout=20.0)
