"""Self-service registration (personal or enterprise space), email sign-in, Bearer tokens, space selection
and space settings. Openspec 2026-11-03-enterprise-personal-spaces, section 2."""
from sqlalchemy import select

from nexus_platform.persistence.models import TenantRecord
from test_auth import CSRF, PASSWORD, client  # noqa: F401  (fixture)
from test_platform import database  # noqa: F401  (fixture)


def _register(client, *, username="ann", email="ann@example.com", kind="personal", name="", code=""):
    return client.post("/api/v1/auth/register", json={
        "username": username, "email": email, "password": PASSWORD, "space_kind": kind,
        "space_name": name, "company_code": code,
    })


def test_personal_registration_creates_one_owned_personal_space(client):
    response = _register(client)
    assert response.status_code == 201, response.text
    space = response.json()["data"]["tenant"]
    assert space["kind"] == "personal"
    login = client.post("/api/v1/auth/login", json={"email": "ann@example.com", "password": PASSWORD})
    assert login.status_code == 200
    assert [(m["id"], m["kind"], m["role"]) for m in login.json()["memberships"]] == [(space["id"], "personal", "owner")]


def test_enterprise_registration_needs_name_and_unique_code(client):
    missing = _register(client, kind="enterprise", name="", code="acme")
    assert missing.status_code == 422
    created = _register(client, kind="enterprise", name="Acme Ltd", code="ACME-01")
    assert created.status_code == 201, created.text
    assert created.json()["data"]["tenant"]["kind"] == "enterprise"
    taken = _register(client, username="bob", email="bob@example.com", kind="enterprise", name="Other", code="acme-01")
    assert taken.status_code == 409 and "企业编码" in taken.json()["error"]["message"]


def test_duplicate_username_and_email_are_refused(client):
    assert _register(client).status_code == 201
    same_name = _register(client, email="other@example.com")
    assert same_name.status_code == 409
    same_mail = _register(client, username="carl", email="ANN@example.com")
    assert same_mail.status_code == 409


def test_registration_can_be_switched_off_in_deployment_file(client, deployment_config):
    deployment_config('[auth]\nmode = "session"\ncookie_secure = false\nregistration_enabled = false\n')
    response = _register(client)
    assert response.status_code == 403
    assert "注册已关闭" in response.json()["error"]["message"]


def test_bearer_token_works_without_cookie_or_csrf_header(client):
    _register(client)
    token = client.post("/api/v1/auth/login", json={"email": "ann@example.com", "password": PASSWORD}).json()["token"]
    client.cookies.clear()
    headers = {"Authorization": f"Bearer {token}"}
    me = client.get("/api/v1/auth/me", headers=headers)
    assert me.status_code == 200 and me.json()["data"]["user"]["email"] == "ann@example.com"
    created = client.post("/api/v1/tenants", json={"name": "Second"}, headers=headers)
    assert created.status_code == 201, created.text
    assert client.post("/api/v1/auth/logout", headers=headers).status_code == 204
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 401


def test_current_space_is_chosen_by_header_and_membership_is_checked(client):
    _register(client)
    _register(client, username="bob", email="bob@example.com", kind="enterprise", name="Bob Co", code="bobco")
    login = client.post("/api/v1/auth/login", json={"email": "ann@example.com", "password": PASSWORD}).json()
    personal = login["memberships"][0]["id"]
    headers = {"Authorization": f"Bearer {login['token']}"}
    client.cookies.clear()
    assert client.get("/api/v1/tenants/current", headers=headers).status_code == 404
    current = client.get("/api/v1/tenants/current", headers={**headers, "X-Tenant-ID": personal})
    assert current.status_code == 200 and current.json()["kind"] == "personal"
    with client.factory() as db:
        other = db.scalar(select(TenantRecord.id).where(TenantRecord.code == "bobco"))
    assert client.post("/api/v1/auth/switch-tenant", json={"tenant_id": str(other)}, headers=headers).status_code == 404
    assert client.get("/api/v1/tenants/current", headers={**headers, "X-Tenant-ID": str(other)}).status_code == 404
    assert client.get("/api/v1/tenants/current", headers={**headers, "X-Tenant-ID": "not-a-uuid"}).status_code == 400


def test_owner_renames_space_and_switch_returns_the_space(client):
    _register(client)
    login = client.post("/api/v1/auth/login", json={"email": "ann@example.com", "password": PASSWORD}).json()
    headers = {"Authorization": f"Bearer {login['token']}", "X-Tenant-ID": login["memberships"][0]["id"]}
    client.cookies.clear()
    switched = client.post("/api/v1/auth/switch-tenant", json={"tenant_id": login["memberships"][0]["id"]}, headers=headers)
    assert switched.status_code == 200 and switched.json()["data"]["tenant"]["role"] == "owner"
    renamed = client.patch("/api/v1/tenants/current", json={"name": "Ann Notes"}, headers=headers)
    assert renamed.status_code == 200 and renamed.json()["name"] == "Ann Notes"


def test_public_auth_config_tells_the_login_page_the_registration_mode(client, deployment_config):
    assert client.get("/api/v1/auth/config").json()["registration_mode"] == "self_serve"
    assert client.get("/api/v1/auth/oidc/config").json() == {"success": True, "enabled": False}
    deployment_config('[auth]\nmode = "session"\ncookie_secure = false\nregistration_enabled = false\n')
    assert client.get("/api/v1/auth/config").json()["registration_mode"] == "invite_only"
