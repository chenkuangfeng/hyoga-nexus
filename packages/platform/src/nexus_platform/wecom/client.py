"""The WeCom server API that the platform needs, as a protocol (openspec 2026-11-11-enterprise-saas E3).

The HTTP implementation lives in ``nexus_connectors.wecom`` and is injected by the API and worker entry points, so
the platform holds no network code and tests use a fake. Every call takes the corp id and one self-built app's
secret; implementations cache access tokens per (corp, secret).

Verified against the official documents on 2026-11-12 (``design.md`` section 6.4):

- sign-in codes are exchanged with ``/cgi-bin/auth/getuserinfo`` and yield ``userid`` for members;
- ``/cgi-bin/department/list`` and ``/cgi-bin/user/simplelist`` return only what lies in the app's visible range;
  names may be withheld unless an administrator authorized them, in which case callers fall back to the ids.
"""
from __future__ import annotations

from typing import Protocol
from urllib.parse import quote

OAUTH_BASE = 'https://open.weixin.qq.com/connect/oauth2/authorize'
QR_BASE = 'https://login.work.weixin.qq.com/wwlogin/sso/login'


class WeComError(Exception):
    """A WeCom call failed. ``code`` is ``unavailable`` (network, token) or ``rejected`` (WeCom refused)."""

    def __init__(self, code: str, detail: str = '') -> None:
        super().__init__(detail or code)
        self.code = code


class WeComApi(Protocol):
    def get_userid(self, corp_id: str, secret: str, code: str) -> str:
        """The member ``userid`` behind a sign-in code; raises WeComError for non-members or refused codes."""

    def list_departments(self, corp_id: str, secret: str) -> list[dict]:
        """``[{'id': str, 'name': str, 'parentid': str}]`` within the app's visible range."""

    def list_members(self, corp_id: str, secret: str, department_id: str) -> list[dict]:
        """``[{'userid': str, 'name': str, 'department': [str]}]`` directly in one department."""

    def send_text(self, corp_id: str, secret: str, agentid: str, userid: str, content: str) -> None:
        """Send an application text message to one member (used by IM channels)."""


def oauth_url(corp_id: str, agentid: str, redirect_uri: str, state: str) -> str:
    """Silent sign-in inside the WeCom client (``snsapi_base``)."""
    return (f'{OAUTH_BASE}?appid={quote(corp_id, safe="")}&redirect_uri={quote(redirect_uri, safe="")}'
            f'&response_type=code&scope=snsapi_base&state={quote(state, safe="")}'
            f'&agentid={quote(agentid, safe="")}#wechat_redirect')


def qr_url(corp_id: str, agentid: str, redirect_uri: str, state: str) -> str:
    """QR sign-in in a desktop browser."""
    return (f'{QR_BASE}?login_type=CorpApp&appid={quote(corp_id, safe="")}&agentid={quote(agentid, safe="")}'
            f'&redirect_uri={quote(redirect_uri, safe="")}&state={quote(state, safe="")}')
