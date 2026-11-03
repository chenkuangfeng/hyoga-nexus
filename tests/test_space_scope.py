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


def test_personal_space_has_no_enterprise_interfaces(client):
    headers, space = _register(client, "solo")
    scoped = {**headers, "X-Tenant-ID": space}
    assert client.post(f"/api/v1/tenants/{space}/members/by-email", headers=scoped,
                       json={"email": "x@example.com", "role": "viewer"}).status_code == 404
    assert client.post(f"/api/v1/tenants/{space}/org-units", headers=scoped, json={"name": "Dept"}).status_code == 404
    assert client.get(f"/api/v1/tenants/{space}/invitations", headers=scoped).status_code == 404
    # Personal spaces still work for their own settings.
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


def test_platform_summary_is_read_only_and_admin_only(client):
    headers, _ = _register(client, "nobody")
    _register(client, "acme-owner", "enterprise", "Acme", "acme")
    assert client.get("/api/v1/admin/summary", headers=headers).status_code == 403
    with client.factory() as db:
        user = db.scalar(select(UserRecord).where(UserRecord.email == "nobody@example.com"))
        user.is_platform_admin = True
        db.commit()
    summary = client.get("/api/v1/admin/summary", headers=headers)
    assert summary.status_code == 200
    assert summary.json() == {"enterprises": 1, "personal_spaces": 1, "shared_spaces": 0}
