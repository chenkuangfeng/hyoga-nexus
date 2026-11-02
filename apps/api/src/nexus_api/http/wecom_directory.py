"""HTTP adapter for WeCom internal-app QR login (`WeComDirectory`).

Reads deployment secrets from the ``[wecom]`` table of configs/nexus.toml, never from the database:
corp_id, agent_id, secret, redirect_uri.
"""
from __future__ import annotations

from urllib.parse import quote

import httpx

from nexus_platform.configuration import DatabaseConfigurationError, wecom_settings
from nexus_platform.errors import ServiceUnavailable, Unauthenticated

API_BASE = "https://qyapi.weixin.qq.com"
QR_BASE = "https://login.work.weixin.qq.com/wwlogin/sso/login"
TIMEOUT = 10.0


class HttpWeComDirectory:
    """Implements `WeComDirectory`; `corp_id` is the provider scope stored with each identity."""

    def __init__(self, corp_id: str, agent_id: str, secret: str, redirect_uri: str):
        self.corp_id, self.agent_id, self.secret, self.redirect_uri = corp_id, agent_id, secret, redirect_uri

    @classmethod
    def from_configuration(cls) -> "HttpWeComDirectory":
        """Build from ``[wecom]``; a missing value or malformed file reports the login as unavailable."""
        try:
            settings = wecom_settings()
        except DatabaseConfigurationError as exc:
            raise ServiceUnavailable("企业微信登录尚未配置") from exc
        if not settings.configured:
            raise ServiceUnavailable("企业微信登录尚未配置")
        return cls(settings.corp_id, settings.agent_id, settings.secret, settings.redirect_uri)

    def authorize_url(self, state: str) -> str:
        return (f"{QR_BASE}?login_type=CorpApp&appid={quote(self.corp_id, safe='')}"
                f"&agentid={quote(self.agent_id, safe='')}&redirect_uri={quote(self.redirect_uri, safe='')}"
                f"&state={quote(state, safe='')}")

    def resolve_user(self, code: str) -> str:
        """Exchange a callback code for the corp member's userid; only members are accepted."""
        try:
            with httpx.Client(timeout=TIMEOUT) as client:
                token = client.get(f"{API_BASE}/cgi-bin/gettoken",
                                   params={"corpid": self.corp_id, "corpsecret": self.secret}).json()
                if token.get("errcode") != 0 or not token.get("access_token"):
                    raise ServiceUnavailable("企业微信服务暂时不可用")
                info = client.get(f"{API_BASE}/cgi-bin/auth/getuserinfo",
                                  params={"access_token": token["access_token"], "code": code}).json()
        except httpx.HTTPError as exc:
            raise ServiceUnavailable("企业微信服务暂时不可用") from exc
        userid = info.get("userid")
        if info.get("errcode") != 0 or not isinstance(userid, str) or not userid:
            raise Unauthenticated("企业微信授权未通过，请重新扫码")
        return userid
