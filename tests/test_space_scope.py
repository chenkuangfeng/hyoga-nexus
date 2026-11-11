"""Permissions by space kind (openspec 2026-11-03, section 4 and 5): personal spaces do not expose enterprise
interfaces (404), enterprise members without the right permission get 403, and platform administrators see
read-only counts only."""
from sqlalchemy import select

from nexus_platform.persistence.models import UserRecord
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


def test_a_registered_one_member_enterprise_has_the_enterprise_interfaces(client):
    """Registration creates an ordinary enterprise (openspec 2026-11-11-enterprise-saas decision 1)."""
    headers, space = _register(client, "solo")
    scoped = {**headers, "X-Tenant-ID": space}
    assert client.post(f"/api/v1/tenants/{space}/org-units", headers=scoped, json={"name": "Dept"}).status_code == 201
    assert client.get(f"/api/v1/tenants/{space}/invitations", headers=scoped).status_code == 200
    assert client.patch("/api/v1/tenants/current", headers=scoped, json={"name": "My notes"}).status_code == 200


def test_enterprise_member_without_permission_gets_403(client):
    owner, acme = _register(client, "owner", "enterprise", "Acme", "acme")
    viewer, viewer_space = _register(client, "vera")
    client.post(f"/api/v1/tenants/{acme}/members/by-email", headers={**owner, "X-Tenant-ID": acme},
                json={"email": "vera@example.com", "role": "viewer"})
    client.post("/api/v1/me/invitations/" + client.get("/api/v1/me/invitations", headers=viewer).json()[0]["id"] + "/accept",
                headers=viewer)
    response = client.post(f"/api/v1/tenants/{acme}/org-units", headers=viewer, json={"name": "Nope"})
    assert response.status_code == 403


def test_cross_enterprise_listings_are_gone(client):
    """Platform administrators no longer list other enterprises' data over HTTP (openspec 2026-11-11 E1.7)."""
    headers, _ = _register(client, "nobody")
    with client.factory() as db:
        user = db.scalar(select(UserRecord).where(UserRecord.email == "nobody@example.com"))
        user.is_platform_admin = True
        db.commit()
    for path in ("/api/v1/admin/summary", "/api/v1/admin/tenants", "/api/v1/admin/agents", "/api/v1/admin/sessions"):
        assert client.get(path, headers=headers).status_code in (404, 405)


def test_enterprise_admin_needs_a_role_for_governance_but_keeps_everyday_access(client):
    owner, acme = _register(client, "owner2", "enterprise", "Beta", "beta")
    admin, _ = _register(client, "adma")
    client.post(f"/api/v1/tenants/{acme}/members/by-email", headers={**owner, "X-Tenant-ID": acme},
                json={"email": "adma@example.com", "role": "admin"})
    client.post("/api/v1/me/invitations/" + client.get("/api/v1/me/invitations", headers=admin).json()[0]["id"] + "/accept",
                headers=admin)
    scoped = {**admin, "X-Tenant-ID": acme}
    # Governance is not part of the built-in admin access.
    assert client.post(f"/api/v1/tenants/{acme}/org-units", headers=scoped, json={"name": "Dept"}).status_code == 403
    assert client.get(f"/api/v1/tenants/{acme}/roles", headers=scoped).status_code == 403
    # Everyday access stays: admins can still use the space's sessions and shared-space settings.
    assert client.get(f"/api/v1/tenants/{acme}/sessions", headers=scoped).status_code == 200
    # Once a custom role grants members:manage, the admin can invite.
    role = client.post(f"/api/v1/tenants/{acme}/roles", headers={**owner, "X-Tenant-ID": acme},
                       json={"name": "People", "menus": [], "apis": ["members:manage"]})
    assert role.status_code == 201, role.text
    adma_id = client.get(f"/api/v1/tenants/{acme}/members", headers={**owner, "X-Tenant-ID": acme}).json()
    member_id = next(m["user_id"] for m in adma_id if m["role"] == "admin")
    assigned = client.put(f"/api/v1/tenants/{acme}/members/{member_id}/roles/{role.json()['id']}",
                          headers={**owner, "X-Tenant-ID": acme})
    assert assigned.status_code == 204, assigned.text
    assert client.post(f"/api/v1/tenants/{acme}/org-units", headers=scoped, json={"name": "Dept"}).status_code == 403
    invited = client.post(f"/api/v1/tenants/{acme}/members/by-email", headers=scoped,
                          json={"email": "newbie@example.com", "role": "viewer"})
    # Permission passes (422 is only the missing username and password for a new email).
    assert invited.status_code == 422
