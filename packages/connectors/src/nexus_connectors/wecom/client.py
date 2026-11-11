"""HTTP implementation of ``nexus_platform.wecom.client.WeComApi`` for self-built apps.

Access tokens are cached per (corp id, secret) until shortly before ``expires_in``; a token WeCom reports as
invalid (errcode 40014 / 42001) is dropped and the call is retried once. Secrets and tokens never appear in errors.
"""
from __future__ import annotations

import threading
import time

import httpx

API_BASE = 'https://qyapi.weixin.qq.com'
TIMEOUT = 10.0
TOKEN_ERRORS = {40014, 42001}


class WeComError(Exception):
    def __init__(self, code: str, detail: str = '') -> None:
        super().__init__(detail or code)
        self.code = code


class HttpWeComApi:
    def __init__(self, *, transport: httpx.BaseTransport | None = None, base_url: str = API_BASE) -> None:
        self._client = httpx.Client(base_url=base_url, timeout=TIMEOUT, transport=transport)
        self._tokens: dict[tuple[str, str], tuple[str, float]] = {}
        self._lock = threading.Lock()

    def _error(self, code: str, detail: str):
        # Raise the platform's error type when it is importable so callers can catch one class.
        try:
            from nexus_platform.wecom.client import WeComError as PlatformError
            return PlatformError(code, detail)
        except ImportError:  # pragma: no cover - connectors used on their own
            return WeComError(code, detail)

    def _token(self, corp_id: str, secret: str, *, fresh: bool = False) -> str:
        key = (corp_id, secret)
        with self._lock:
            cached = self._tokens.get(key)
            if cached and not fresh and cached[1] > time.monotonic():
                return cached[0]
        try:
            data = self._client.get('/cgi-bin/gettoken', params={'corpid': corp_id, 'corpsecret': secret}).json()
        except (httpx.HTTPError, ValueError) as exc:
            raise self._error('unavailable', 'WeCom token request failed') from exc
        if data.get('errcode') != 0 or not data.get('access_token'):
            raise self._error('rejected', f"WeCom refused the app credentials (errcode {data.get('errcode')})")
        with self._lock:
            self._tokens[key] = (data['access_token'], time.monotonic() + max(60, int(data.get('expires_in', 7200)) - 300))
        return data['access_token']

    def _get(self, corp_id: str, secret: str, path: str, params: dict) -> dict:
        for attempt in range(2):
            token = self._token(corp_id, secret, fresh=attempt == 1)
            try:
                data = self._client.get(path, params={**params, 'access_token': token}).json()
            except (httpx.HTTPError, ValueError) as exc:
                raise self._error('unavailable', f'WeCom request {path} failed') from exc
            if data.get('errcode') in TOKEN_ERRORS and attempt == 0:
                continue
            if data.get('errcode') != 0:
                raise self._error('rejected', f"WeCom refused {path} (errcode {data.get('errcode')})")
            return data
        raise self._error('rejected', f'WeCom refused {path}')

    def get_userid(self, corp_id: str, secret: str, code: str) -> str:
        data = self._get(corp_id, secret, '/cgi-bin/auth/getuserinfo', {'code': code})
        userid = data.get('userid') or data.get('UserId')
        if not isinstance(userid, str) or not userid:
            raise self._error('rejected', 'The signed-in person is not a member of this corp')
        return userid

    def list_departments(self, corp_id: str, secret: str) -> list[dict]:
        data = self._get(corp_id, secret, '/cgi-bin/department/list', {})
        return [{'id': str(item['id']), 'name': str(item.get('name') or item['id']),
                 'parentid': str(item.get('parentid', 0))} for item in data.get('department') or []]

    def list_members(self, corp_id: str, secret: str, department_id: str) -> list[dict]:
        data = self._get(corp_id, secret, '/cgi-bin/user/simplelist', {'department_id': department_id})
        return [{'userid': str(item['userid']), 'name': str(item.get('name') or ''),
                 'department': [str(dept) for dept in item.get('department') or []]}
                for item in data.get('userlist') or []]

    def send_text(self, corp_id: str, secret: str, agentid: str, userid: str, content: str) -> None:
        for attempt in range(2):
            token = self._token(corp_id, secret, fresh=attempt == 1)
            try:
                data = self._client.post('/cgi-bin/message/send', params={'access_token': token}, json={
                    'touser': userid, 'msgtype': 'text', 'agentid': int(agentid), 'text': {'content': content}}).json()
            except (httpx.HTTPError, ValueError) as exc:
                raise self._error('unavailable', 'WeCom message send failed') from exc
            if data.get('errcode') in TOKEN_ERRORS and attempt == 0:
                continue
            if data.get('errcode') != 0:
                raise self._error('rejected', f"WeCom refused the message (errcode {data.get('errcode')})")
            return
