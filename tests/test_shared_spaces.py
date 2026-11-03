"""Shared spaces (WeKnora organizations, named shared spaces here): creation, invite codes, joining, approval,
role upgrades, leaving and deletion. Openspec 2026-11-03-enterprise-personal-spaces, section 4.

Spaces join, not people: each call acts for one space through `X-Tenant-ID`."""
from test_auth import PASSWORD, client  # noqa: F401  (fixture)
from test_platform import database  # noqa: F401  (fixture)


def _register(client, username, kind="personal", name="", code=""):
    response = client.post("/api/v1/auth/register", json={
        "username": username, "email": f"{username}@example.com", "password": PASSWORD,
        "space_kind": kind, "space_name": name, "company_code": code,
    })
    assert response.status_code == 201, response.text
    token = client.post("/api/v1/auth/login", json={"email": f"{username}@example.com", "password": PASSWORD}).json()["token"]
    return {"Authorization": f"Bearer {token}"}, response.json()["data"]["tenant"]["id"]


def _as(headers, space):
    return {**headers, "X-Tenant-ID": space}


def test_owner_creates_shared_space_and_invite_code_lets_another_space_join(client):
    ann, acme = _register(client, "ann", "enterprise", "Acme", "acme")
    created = client.post("/api/v1/shared-spaces", json={"name": "Alliance"}, headers=_as(ann, acme))
    assert created.status_code == 201, created.text
    shared = created.json()["id"]
    assert client.get("/api/v1/shared-spaces", headers=_as(ann, acme)).json()[0]["role"] == "admin"

    code = client.post(f"/api/v1/shared-spaces/{shared}/invite-code", headers=_as(ann, acme)).json()["invite_code"]
    bob, bob_space = _register(client, "bob")
    preview = client.get(f"/api/v1/shared-spaces/preview/{code}", headers=bob)
    assert preview.status_code == 200 and preview.json()["name"] == "Alliance"
    joined = client.post("/api/v1/shared-spaces/join", json={"invite_code": code}, headers=_as(bob, bob_space))
    assert joined.status_code == 200 and joined.json()["role"] == "viewer", joined.text
    bob_view = client.get(f"/api/v1/shared-spaces/{shared}", headers=_as(bob, bob_space)).json()
    assert bob_view["role"] == "viewer" and {m["tenant_id"] for m in bob_view["members"]} == {acme, bob_space}
    assert "invite_code" not in bob_view  # only shared admins see the code
    # A viewer cannot change the shared space.
    assert client.put(f"/api/v1/shared-spaces/{shared}", json={"name": "Hacked"}, headers=_as(bob, bob_space)).status_code == 403


def test_direct_join_needs_searchable_and_approval_turns_joins_into_requests(client):
    ann, acme = _register(client, "ann", "enterprise", "Acme", "acme")
    shared = client.post("/api/v1/shared-spaces", json={"name": "Open"}, headers=_as(ann, acme)).json()["id"]
    carl, carl_space = _register(client, "carl")
    assert client.post("/api/v1/shared-spaces/join-by-id", json={"shared_space_id": shared},
                       headers=_as(carl, carl_space)).status_code == 403
    client.put(f"/api/v1/shared-spaces/{shared}", json={"searchable": True, "require_approval": True}, headers=_as(ann, acme))
    found = client.get("/api/v1/shared-spaces/search?q=open", headers=carl).json()
    assert [row["name"] for row in found] == ["Open"]
    pending = client.post("/api/v1/shared-spaces/join-by-id", json={"shared_space_id": shared},
                          headers=_as(carl, carl_space))
    assert pending.status_code == 200 and pending.json()["status"] == "pending"
    requests = client.get(f"/api/v1/shared-spaces/{shared}/join-requests", headers=_as(ann, acme)).json()
    assert len(requests) == 1 and requests[0]["request_type"] == "join"
    approved = client.post(f"/api/v1/shared-spaces/{shared}/join-requests/{requests[0]['id']}/approve",
                           json={}, headers=_as(ann, acme))
    assert approved.status_code == 200 and approved.json()["status"] == "approved"
    assert client.get(f"/api/v1/shared-spaces/{shared}", headers=_as(carl, carl_space)).json()["role"] == "viewer"


def test_role_upgrade_request_is_reviewed_and_applied(client):
    ann, acme = _register(client, "ann", "enterprise", "Acme", "acme")
    shared = client.post("/api/v1/shared-spaces", json={"name": "Club"}, headers=_as(ann, acme)).json()["id"]
    code = client.post(f"/api/v1/shared-spaces/{shared}/invite-code", headers=_as(ann, acme)).json()["invite_code"]
    dan, dan_space = _register(client, "dan")
    client.post("/api/v1/shared-spaces/join", json={"invite_code": code}, headers=_as(dan, dan_space))
    upgrade = client.post(f"/api/v1/shared-spaces/{shared}/request-upgrade", json={"requested_role": "editor"},
                          headers=_as(dan, dan_space))
    assert upgrade.status_code == 201, upgrade.text
    request_id = client.get(f"/api/v1/shared-spaces/{shared}/join-requests", headers=_as(ann, acme)).json()[0]["id"]
    client.post(f"/api/v1/shared-spaces/{shared}/join-requests/{request_id}/approve", json={}, headers=_as(ann, acme))
    assert client.get(f"/api/v1/shared-spaces/{shared}", headers=_as(dan, dan_space)).json()["role"] == "editor"


def test_creating_space_cannot_leave_and_others_can_leave_and_only_creator_deletes(client):
    ann, acme = _register(client, "ann", "enterprise", "Acme", "acme")
    shared = client.post("/api/v1/shared-spaces", json={"name": "Temp"}, headers=_as(ann, acme)).json()["id"]
    code = client.post(f"/api/v1/shared-spaces/{shared}/invite-code", headers=_as(ann, acme)).json()["invite_code"]
    eve, eve_space = _register(client, "eve")
    client.post("/api/v1/shared-spaces/join", json={"invite_code": code}, headers=_as(eve, eve_space))
    assert client.post(f"/api/v1/shared-spaces/{shared}/leave", headers=_as(ann, acme)).status_code == 409
    assert client.delete(f"/api/v1/shared-spaces/{shared}", headers=_as(eve, eve_space)).status_code == 403
    assert client.post(f"/api/v1/shared-spaces/{shared}/leave", headers=_as(eve, eve_space)).status_code == 204
    assert client.get("/api/v1/shared-spaces", headers=_as(eve, eve_space)).json() == []
    assert client.delete(f"/api/v1/shared-spaces/{shared}", headers=_as(ann, acme)).status_code == 204
    assert client.get(f"/api/v1/shared-spaces/{shared}", headers=_as(ann, acme)).status_code == 404


def test_acting_requires_a_space_header_and_shared_admin_role_for_settings(client):
    ann, acme = _register(client, "ann", "enterprise", "Acme", "acme")
    shared = client.post("/api/v1/shared-spaces", json={"name": "Hub"}, headers=_as(ann, acme)).json()["id"]
    # Without a current space there is nothing to act for.
    assert client.get("/api/v1/shared-spaces", headers=ann).status_code == 400
    code = client.post(f"/api/v1/shared-spaces/{shared}/invite-code", headers=_as(ann, acme)).json()["invite_code"]
    bob, bob_space = _register(client, "bob")
    client.post("/api/v1/shared-spaces/join", json={"invite_code": code}, headers=_as(bob, bob_space))
    # A viewer space cannot issue invite codes or read the code itself.
    assert client.post(f"/api/v1/shared-spaces/{shared}/invite-code", headers=_as(bob, bob_space)).status_code == 403
    assert client.get(f"/api/v1/shared-spaces/{shared}/join-requests", headers=_as(bob, bob_space)).status_code == 403
    assert client.post("/api/v1/shared-spaces/join", json={"invite_code": "unknown-code"},
                       headers=_as(bob, bob_space)).status_code == 404


def test_enterprise_with_active_shared_space_cannot_be_deleted_until_it_is_removed(client):
    ann, acme = _register(client, "ann", kind="enterprise", name="Acme", code="acme-del")
    acme_id = client.get("/api/v1/auth/me", headers=ann).json()["data"]["memberships"][0]["id"]
    shared = client.post("/api/v1/shared-spaces", json={"name": "Alliance"}, headers=_as(ann, acme)).json()["id"]
    blocked = client.delete(f"/api/v1/tenants/{acme_id}", headers=ann)
    assert blocked.status_code == 409, blocked.text
    removed = client.delete(f"/api/v1/shared-spaces/{shared}", headers=_as(ann, acme))
    assert removed.status_code in (200, 204), removed.text
    archived = client.delete(f"/api/v1/tenants/{acme_id}", headers=ann)
    assert archived.status_code == 204, archived.text
