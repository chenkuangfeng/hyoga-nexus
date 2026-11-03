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


def _login(client, email="ann@example.com"):
    response = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200, response.text
    return response.json()


def test_preferences_remember_the_space_opened_at_sign_in(client):
    _register(client)
    login = _login(client)
    assert login["user"]["preferences"] == {}
    personal = next(m["id"] for m in login["memberships"] if m["kind"] == "personal")
    # The home space is the personal space until a preference is saved.
    assert login["active_tenant"]["id"] == personal

    headers = {"Authorization": f"Bearer {login['token']}"}
    second = client.post("/api/v1/tenants", json={"name": "Second"}, headers=headers)
    assert second.status_code == 201, second.text
    second_space = second.json()["id"]
    saved = client.put("/api/v1/auth/me/preferences", json={"last_active_tenant_id": second_space}, headers=headers)
    assert saved.status_code == 200, saved.text
    assert saved.json()["data"]["preferences"] == {"last_active_tenant_id": second_space}
    assert _login(client)["active_tenant"]["id"] == second_space
    assert client.get("/api/v1/auth/me", headers=headers).json()["data"]["user"]["preferences"] == {
        "last_active_tenant_id": second_space}

    cleared = client.put("/api/v1/auth/me/preferences", json={"last_active_tenant_id": None}, headers=headers)
    assert cleared.json()["data"]["preferences"] == {}
    assert _login(client)["active_tenant"]["id"] == personal


def test_preferences_refuse_unknown_keys_and_spaces_the_user_is_not_in(client):
    _register(client)
    _register(client, username="work", email="work@example.com", kind="enterprise", name="Work Co", code="WORK-2")
    headers = {"Authorization": f"Bearer {_login(client)['token']}"}
    unknown = client.put("/api/v1/auth/me/preferences", json={"theme": "dark"}, headers=headers)
    assert unknown.status_code == 422
    other = _login(client, "work@example.com")
    foreign = other["memberships"][0]["id"]
    refused = client.put("/api/v1/auth/me/preferences", json={"last_active_tenant_id": foreign}, headers=headers)
    assert refused.status_code == 404
    malformed = client.put("/api/v1/auth/me/preferences", json={"last_active_tenant_id": "not-a-uuid"},
                           headers=headers)
    assert malformed.status_code == 422


def test_membership_view_carries_tenant_id_and_name(client):
    _register(client)
    login = _login(client)
    entry = login["memberships"][0]
    assert entry["tenant_id"] == entry["id"]
    assert entry["tenant_name"] == entry["name"]


def test_ui_preferences_are_stored_as_given_and_cleared_with_null(client):
    _register(client)
    headers = {"Authorization": f"Bearer {_login(client)['token']}"}
    saved = client.put("/api/v1/auth/me/preferences", headers=headers,
                       json={"browser_search_instructions": "only news", "gallery": {"mode": "custom"}})
    assert saved.status_code == 200, saved.text
    assert saved.json()["data"]["preferences"] == {"browser_search_instructions": "only news",
                                                   "gallery": {"mode": "custom"}}
    cleared = client.put("/api/v1/auth/me/preferences", headers=headers, json={"gallery": None})
    assert cleared.json()["data"]["preferences"] == {"browser_search_instructions": "only news"}


def test_owner_or_admin_edits_name_and_description_and_clears_description(client):
    _register(client, kind="enterprise", name="Acme", code="ACME-SET")
    login = _login(client)
    headers = {"Authorization": f"Bearer {login['token']}"}
    space_headers = {**headers, "X-Tenant-ID": login["memberships"][0]["id"]}
    described = client.patch("/api/v1/tenants/current", headers=space_headers,
                             json={"description": "Hardware and services"})
    assert described.status_code == 200, described.text
    assert described.json()["description"] == "Hardware and services"
    renamed = client.patch("/api/v1/tenants/current", headers=space_headers, json={"name": "Acme Holdings"})
    assert renamed.json()["name"] == "Acme Holdings"
    assert renamed.json()["description"] == "Hardware and services"
    cleared = client.patch("/api/v1/tenants/current", headers=space_headers, json={"description": ""})
    assert cleared.json()["description"] is None
    empty = client.patch("/api/v1/tenants/current", headers=space_headers, json={})
    assert empty.status_code == 422
    too_long = client.patch("/api/v1/tenants/current", headers=space_headers, json={"description": "x" * 501})
    assert too_long.status_code == 422


def test_owner_archives_enterprise_space_and_it_disappears(client):
    _register(client, kind="enterprise", name="Gone Co", code="GONE-CO")
    headers = {"Authorization": f"Bearer {_login(client)['token']}"}
    space_id = _login(client)["memberships"][0]["id"]
    deleted = client.delete(f"/api/v1/tenants/{space_id}", headers=headers)
    assert deleted.status_code == 204, deleted.text
    after = _login(client)
    assert space_id not in [m["id"] for m in after["memberships"]]
    gone = client.get("/api/v1/tenants/current", headers={**headers, "X-Tenant-ID": space_id})
    assert gone.status_code == 404


def test_personal_space_cannot_be_deleted(client):
    _register(client)
    login = _login(client)
    headers = {"Authorization": f"Bearer {login['token']}"}
    personal = login["active_tenant"]["id"]
    refused = client.delete(f"/api/v1/tenants/{personal}", headers=headers)
    assert refused.status_code == 403
    assert "personal space" in refused.json()["error"]["message"]


def test_admin_cannot_delete_enterprise_space(client):
    _register(client, kind="enterprise", name="Owned Co", code="OWNED-CO")
    owner = {"Authorization": f"Bearer {_login(client)['token']}"}
    space_id = next(m["id"] for m in _login(client)["memberships"] if m["kind"] == "enterprise")
    _register(client, username="ops", email="ops@example.com")
    ops_token = _login(client, "ops@example.com")["token"]
    ops = {"Authorization": f"Bearer {ops_token}"}
    ops_space = {**ops, "X-Tenant-ID": space_id}
    invited = client.post(f"/api/v1/tenants/{space_id}/members/by-email", headers=owner,
                          json={"email": "ops@example.com", "role": "admin"})
    assert invited.status_code == 201, invited.text
    inv_id = client.get("/api/v1/me/invitations", headers=ops).json()[0]["id"]
    assert client.post(f"/api/v1/me/invitations/{inv_id}/accept", headers=ops).status_code in (200, 204)
    refused = client.delete(f"/api/v1/tenants/{space_id}", headers=ops_space)
    assert refused.status_code == 403
