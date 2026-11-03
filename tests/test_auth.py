"""Login mechanisms: password accounts with lockout, server-side sessions with CSRF, WeCom QR login
and binding, and operator owner bootstrap. WeCom is replaced by a fake directory."""
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from nexus_api.dependencies.platform import get_database_session
from nexus_api.main import app
from nexus_core.platform import Principal, TenantRole
from nexus_platform.auth import accounts, sessions, wecom
from nexus_platform.errors import Conflict, Unauthenticated
from nexus_platform.persistence.models import AuthSessionRecord, UserIdentityRecord
from test_platform import database  # noqa: F401  (fixture)

CSRF = {"X-Nexus-Request": "1"}
PASSWORD = "correct-horse-battery"


class FakeWeCom:
    corp_id = "corp-1"

    def __init__(self):
        self.users = {"code-zhang": "zhangsan", "code-li": "lisi"}

    def authorize_url(self, state):
        return f"https://qr.example/login?state={state}"

    def resolve_user(self, code):
        from nexus_platform.errors import Unauthenticated as Denied
        if code not in self.users:
            raise Denied("企业微信授权未通过，请重新扫码")
        return self.users[code]


@pytest.fixture
def client(database, deployment_config):
    deployment_config('[auth]\nmode = "session"\ncookie_secure = false\n')
    fake = FakeWeCom()
    app.state.session_factory = database
    app.state.wecom_directory = fake

    def override_db():
        with database() as db:
            yield db

    app.dependency_overrides[get_database_session] = override_db
    try:
        with TestClient(app, follow_redirects=False) as test_client:
            test_client.fake = fake
            test_client.factory = database
            yield test_client
    finally:
        app.dependency_overrides.clear()
        app.state.session_factory = None
        app.state.wecom_directory = None


def _bootstrap_owner(factory, username="owner-one"):
    with factory() as db:
        return accounts.create_owner_account(db, tenant_name="Acme", username=username,
                                             display_name="Owner", password=PASSWORD)


def _login(client, username, password=PASSWORD):
    return client.post("/api/v1/auth/login", json={"username": username, "password": password}, headers=CSRF)


def test_password_login_sets_http_only_cookie_and_logout_revokes(client):
    tenant_id = _bootstrap_owner(client.factory)
    assert client.get("/api/v1/tenants").status_code == 401
    response = _login(client, "owner-one")
    assert response.status_code == 204, response.text
    cookie = response.headers["set-cookie"]
    assert "nexus_session=" in cookie and "HttpOnly" in cookie and "SameSite=lax" in cookie
    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200 and me.json()["providers"] == ["password"]
    assert client.get("/api/v1/tenants").json()[0]["id"] == str(tenant_id)
    assert client.post("/api/v1/tenants", json={"name": "No header"}).status_code == 403
    assert client.post("/api/v1/auth/logout").status_code == 403
    assert client.post("/api/v1/auth/logout", headers=CSRF).status_code == 204
    assert client.get("/api/v1/auth/me").status_code == 401


def test_failures_are_generic_and_lock_after_five_attempts(client):
    _bootstrap_owner(client.factory)
    unknown = _login(client, "nobody-here", PASSWORD)
    wrong = _login(client, "owner-one", "wrong-password-value")
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json()["error"]["message"] == wrong.json()["error"]["message"] == "用户名或密码错误"
    for _ in range(4):
        _login(client, "owner-one", "wrong-password-value")
    locked = _login(client, "owner-one", PASSWORD)
    assert locked.status_code == 401
    assert "锁定" in locked.json()["error"]["message"]


def test_session_tokens_are_stored_only_as_digest(client):
    _bootstrap_owner(client.factory)
    _login(client, "owner-one")
    token = client.cookies.get("nexus_session")
    with client.factory() as db:
        ids = list(db.scalars(select(AuthSessionRecord.id)))
    assert token not in ids and sessions.digest(token) in ids


def test_password_change_revokes_sessions_and_requires_current_password(client):
    _bootstrap_owner(client.factory)
    _login(client, "owner-one")
    bad = client.post("/api/v1/auth/password", json={"current_password": "not-the-password", "new_password": "brand-new-password"}, headers=CSRF)
    assert bad.status_code == 401
    ok = client.post("/api/v1/auth/password", json={"current_password": PASSWORD, "new_password": "brand-new-password"}, headers=CSRF)
    assert ok.status_code == 204, ok.text
    assert client.get("/api/v1/auth/me").status_code == 401
    assert _login(client, "owner-one", PASSWORD).status_code == 401
    assert _login(client, "owner-one", "brand-new-password").status_code == 204


def test_admin_creates_member_account_and_member_logs_in(client):
    _bootstrap_owner(client.factory)
    _login(client, "owner-one")
    tenant_id = client.get("/api/v1/tenants").json()[0]["id"]
    created = client.post(f"/api/v1/tenants/{tenant_id}/accounts", headers=CSRF,
                          json={"username": "Staff.One", "display_name": "Staff", "password": "staff-password-1", "role": "contributor"})
    assert created.status_code == 201, created.text
    assert created.json()["username"] == "staff.one"
    duplicate = client.post(f"/api/v1/tenants/{tenant_id}/accounts", headers=CSRF,
                            json={"username": "staff.one", "password": "another-password-1"})
    assert duplicate.status_code == 409
    client.post("/api/v1/auth/logout", headers=CSRF)
    assert _login(client, "staff.one", "staff-password-1").status_code == 204
    assert client.get(f"/api/v1/tenants/{tenant_id}/roles").status_code == 403


def test_wecom_login_requires_binding_and_reusing_state_fails(client):
    _bootstrap_owner(client.factory)
    start = client.get("/api/v1/auth/wecom/start")
    assert start.status_code == 302
    state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
    unbound = client.get(f"/api/v1/auth/wecom/callback?code=code-zhang&state={state}")
    assert unbound.status_code == 303 and "error=unbound" in unbound.headers["location"]
    replay = client.get(f"/api/v1/auth/wecom/callback?code=code-zhang&state={state}")
    assert replay.status_code == 303 and "error=failed" in replay.headers["location"]


def test_wecom_bind_then_login_by_qr(client):
    _bootstrap_owner(client.factory)
    _login(client, "owner-one")
    bind = client.post("/api/v1/auth/wecom/bind/start", headers=CSRF)
    assert bind.status_code == 200, bind.text
    state = parse_qs(urlparse(bind.json()["authorize_url"]).query)["state"][0]
    bound = client.get(f"/api/v1/auth/wecom/callback?code=code-zhang&state={state}")
    assert bound.status_code == 303 and "wecom=bound" in bound.headers["location"]
    with client.factory() as db:
        row = db.scalar(select(UserIdentityRecord).where(UserIdentityRecord.provider == "wecom"))
        assert (row.scope, row.external_id) == ("corp-1", "zhangsan")
    client.post("/api/v1/auth/logout", headers=CSRF)
    start = client.get("/api/v1/auth/wecom/start")
    login_state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
    signed_in = client.get(f"/api/v1/auth/wecom/callback?code=code-zhang&state={login_state}")
    assert signed_in.status_code == 303 and signed_in.headers["location"] == "/chat"
    assert "nexus_session=" in signed_in.headers["set-cookie"]
    assert client.get("/api/v1/auth/me").json()["providers"] == ["password", "wecom"]


def test_wecom_identity_cannot_bind_to_two_users(client):
    _bootstrap_owner(client.factory)
    _login(client, "owner-one")
    state = parse_qs(urlparse(client.post("/api/v1/auth/wecom/bind/start", headers=CSRF).json()["authorize_url"]).query)["state"][0]
    client.get(f"/api/v1/auth/wecom/callback?code=code-zhang&state={state}")
    client.post("/api/v1/auth/logout", headers=CSRF)
    with client.factory() as db:
        tenant_id = accounts.create_owner_account(db, tenant_name="Other", username="owner-two",
                                                  display_name="Two", password=PASSWORD)
    _login(client, "owner-two")
    state = parse_qs(urlparse(client.post("/api/v1/auth/wecom/bind/start", headers=CSRF).json()["authorize_url"]).query)["state"][0]
    result = client.get(f"/api/v1/auth/wecom/callback?code=code-zhang&state={state}")
    assert "wecom=conflict" in result.headers["location"]


def test_expired_session_is_rejected(client):
    from datetime import timedelta
    from nexus_core.platform import utc_now
    _bootstrap_owner(client.factory)
    _login(client, "owner-one")
    token = client.cookies.get("nexus_session")
    with client.factory() as db, db.begin():
        row = db.get(AuthSessionRecord, sessions.digest(token))
        row.expires_at = utc_now() - timedelta(seconds=1)
    assert client.get("/api/v1/auth/me").status_code == 401


def test_owner_bootstrap_rejects_duplicate_username(database):
    with database() as db:
        accounts.create_owner_account(db, tenant_name="A", username="dup-user", display_name="", password=PASSWORD)
    with database() as db:
        with pytest.raises(Conflict):
            accounts.create_owner_account(db, tenant_name="B", username="dup-user", display_name="", password=PASSWORD)


def test_short_password_rejected_without_storing_anything(database):
    with database() as db:
        with pytest.raises(ValueError):
            accounts.create_owner_account(db, tenant_name="C", username="short-pass", display_name="", password="short")


def test_password_hash_roundtrip_and_malformed_values():
    from nexus_platform.auth.passwords import hash_password, verify_password
    stored = hash_password(PASSWORD)
    assert verify_password(PASSWORD, stored) and not verify_password("wrong-password-x", stored)
    assert not verify_password(PASSWORD, "not-a-hash") and not verify_password(PASSWORD, "scrypt$x$y$z$a$b")
