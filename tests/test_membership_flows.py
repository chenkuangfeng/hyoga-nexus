"""Members, invitations, join applications, leaving and batch roles by node (openspec 2026-11-03, section 3).

Drives the HTTP API with Bearer tokens. The owner runs an enterprise space; the other people are ordinary
accounts that join through the flows under test."""
from uuid import UUID

from sqlalchemy import select

from nexus_platform.persistence.models import MembershipRecord, UserOrgUnitRecord
from test_auth import PASSWORD, client  # noqa: F401  (fixture)
from test_platform import database  # noqa: F401  (fixture)


def _register(client, username, email, kind="personal", name="", code=""):
    response = client.post("/api/v1/auth/register", json={
        "username": username, "email": email, "password": PASSWORD, "space_kind": kind,
        "space_name": name, "company_code": code,
    })
    assert response.status_code == 201, response.text
    return response.json()["data"]["tenant"]["id"]


def _token(client, email, password=PASSWORD):
    response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['token']}"}


def _space_headers(client, email, space_id):
    return {**_token(client, email), "X-Tenant-ID": space_id}


def _role_in(client, email, space_id):
    with client.factory() as db:
        from nexus_platform.persistence.models import UserRecord
        user = db.scalar(select(UserRecord).where(UserRecord.email == email))
        row = db.get(MembershipRecord, (UUID(space_id), user.id))
        return None if row is None else (row.role, row.status, row.source)


def _owner_space(client):
    _register(client, "owner-acme", "owner@acme.example", kind="enterprise", name="Acme", code="acme")
    with client.factory() as db:
        from nexus_platform.persistence.models import TenantRecord
        space_id = str(db.scalar(select(TenantRecord.id).where(TenantRecord.code == "acme")))
    return space_id, _space_headers(client, "owner@acme.example", space_id)


def test_invite_existing_account_then_accept_activates_membership(client):
    space_id, owner = _owner_space(client)
    _register(client, "bob", "bob@example.com")
    invited = client.post(f"/api/v1/tenants/{space_id}/members/by-email", headers=owner,
                          json={"email": "bob@example.com", "role": "viewer"})
    assert invited.status_code == 201, invited.text
    assert invited.json()["status"] == "invited"
    duplicate = client.post(f"/api/v1/tenants/{space_id}/members/by-email", headers=owner,
                            json={"email": "bob@example.com", "role": "viewer"})
    assert duplicate.status_code == 409
    bob = _token(client, "bob@example.com")
    pending = client.get("/api/v1/me/invitations", headers=bob).json()
    assert [(p["tenant_name"], p["role"]) for p in pending] == [("Acme", "viewer")]
    assert client.get("/api/v1/me/invitations/pending-count", headers=bob).json() == {"count": 1}
    accepted = client.post(f"/api/v1/me/invitations/{pending[0]['id']}/accept", headers=bob)
    assert accepted.status_code == 200 and accepted.json()["status"] == "approved"
    assert _role_in(client, "bob@example.com", space_id) == ("viewer", "active", "invitation")


def test_declined_invitation_leaves_no_membership(client):
    space_id, owner = _owner_space(client)
    _register(client, "bob", "bob@example.com")
    client.post(f"/api/v1/tenants/{space_id}/members/by-email", headers=owner,
                json={"email": "bob@example.com", "role": "contributor"})
    bob = _token(client, "bob@example.com")
    invitation = client.get("/api/v1/me/invitations", headers=bob).json()[0]["id"]
    assert client.post(f"/api/v1/me/invitations/{invitation}/decline", headers=bob).json()["status"] == "rejected"
    assert _role_in(client, "bob@example.com", space_id) is None


def test_new_email_needs_username_and_password_then_creates_account_in_node(client):
    space_id, owner = _owner_space(client)
    unit = client.post(f"/api/v1/tenants/{space_id}/org-units", headers=owner, json={"name": "Acme Group"}).json()["id"]
    missing = client.post(f"/api/v1/tenants/{space_id}/members/by-email", headers=owner,
                          json={"email": "new@example.com", "role": "contributor"})
    assert missing.status_code == 422
    created = client.post(f"/api/v1/tenants/{space_id}/members/by-email", headers=owner, json={
        "email": "new@example.com", "role": "contributor", "username": "newcomer", "password": "temp-password-1",
        "unit_id": unit,
    })
    assert created.status_code == 201, created.text
    signed_in = client.post("/api/v1/auth/login", json={"email": "new@example.com", "password": "temp-password-1"})
    assert signed_in.json()["user"]["must_change_password"] is True
    assert _role_in(client, "new@example.com", space_id) == ("contributor", "active", "manual")
    with client.factory() as db:
        assert db.scalar(select(UserOrgUnitRecord.is_primary).where(UserOrgUnitRecord.unit_id == UUID(unit))) is True


def test_members_without_members_manage_cannot_invite(client):
    space_id, owner = _owner_space(client)
    _register(client, "viewer-vee", "vee@example.com")
    client.post(f"/api/v1/tenants/{space_id}/members/by-email", headers=owner,
                json={"email": "vee@example.com", "role": "viewer"})
    vee = _token(client, "vee@example.com")
    client.post(f"/api/v1/me/invitations/{client.get('/api/v1/me/invitations', headers=vee).json()[0]['id']}/accept",
                headers=vee)
    response = client.post(f"/api/v1/tenants/{space_id}/members/by-email", headers=vee,
                           json={"email": "x@example.com", "role": "viewer"})
    assert response.status_code == 403


def test_application_needs_an_outsider_and_approval_needs_node_and_role(client):
    space_id, owner = _owner_space(client)
    own = _register(client, "carl", "carl@example.com")  # registration creates carl's own enterprise
    carl = _token(client, "carl@example.com")
    refused = client.post(f"/api/v1/tenants/{own}/join-requests", headers=carl, json={"message": "hi"})
    assert refused.status_code == 409  # already a member of it
    applied = client.post(f"/api/v1/tenants/{space_id}/join-requests", headers=carl, json={"message": "Hello"})
    assert applied.status_code == 201, applied.text
    assert client.post(f"/api/v1/tenants/{space_id}/join-requests", headers=carl, json={}).status_code == 409
    application = applied.json()["id"]
    unit = client.post(f"/api/v1/tenants/{space_id}/org-units", headers=owner, json={"name": "Sales"}).json()["id"]
    assert [a["email"] for a in client.get(f"/api/v1/tenants/{space_id}/join-requests", headers=owner).json()] == [
        "carl@example.com"]
    approved = client.post(f"/api/v1/tenants/{space_id}/join-requests/{application}/approve", headers=owner,
                           json={"unit_id": unit, "role": "contributor"})
    assert approved.status_code == 200, approved.text
    assert _role_in(client, "carl@example.com", space_id) == ("contributor", "active", "application")


def test_rejection_needs_reason_and_blocks_reapplying_for_seven_days(client):
    space_id, owner = _owner_space(client)
    _register(client, "dan", "dan@example.com")
    dan = _token(client, "dan@example.com")
    application = client.post(f"/api/v1/tenants/{space_id}/join-requests", headers=dan, json={}).json()["id"]
    assert client.post(f"/api/v1/tenants/{space_id}/join-requests/{application}/reject", headers=owner,
                       json={"reason": "   "}).status_code == 422
    rejected = client.post(f"/api/v1/tenants/{space_id}/join-requests/{application}/reject", headers=owner,
                           json={"reason": "Not in scope"})
    assert rejected.status_code == 204
    again = client.post(f"/api/v1/tenants/{space_id}/join-requests", headers=dan, json={})
    assert again.status_code == 403 and "cooldown" in again.json()["error"]["message"]


def test_applicant_can_withdraw_and_owner_cannot_leave(client):
    space_id, owner = _owner_space(client)
    _register(client, "erin", "erin@example.com")
    erin = _token(client, "erin@example.com")
    application = client.post(f"/api/v1/tenants/{space_id}/join-requests", headers=erin, json={}).json()["id"]
    assert client.delete(f"/api/v1/tenants/{space_id}/join-requests/{application}", headers=owner).status_code == 404
    assert client.delete(f"/api/v1/tenants/{space_id}/join-requests/{application}", headers=erin).status_code == 204
    assert client.post(f"/api/v1/tenants/{space_id}/leave", headers=owner).status_code == 409


def test_member_leaves_and_role_is_granted_to_everyone_in_a_node(client):
    space_id, owner = _owner_space(client)
    unit = client.post(f"/api/v1/tenants/{space_id}/org-units", headers=owner, json={"name": "Ops"}).json()["id"]
    role = client.post(f"/api/v1/tenants/{space_id}/roles", headers=owner,
                       json={"name": "Reader", "menus": [], "apis": ["agents:read"]})
    assert role.status_code == 201, role.text
    role_id = role.json()["id"]
    _register(client, "fay", "fay@example.com")
    client.post(f"/api/v1/tenants/{space_id}/members/by-email", headers=owner,
                json={"email": "fay@example.com", "role": "contributor", "unit_id": unit})
    fay = _token(client, "fay@example.com")
    client.post(f"/api/v1/me/invitations/{client.get('/api/v1/me/invitations', headers=fay).json()[0]['id']}/accept",
                headers=fay)
    first = client.post(f"/api/v1/tenants/{space_id}/org-units/{unit}/role-assignments", headers=owner, json={"role_id": role_id})
    assert first.status_code == 200 and len(first.json()["assigned"]) == 1 and first.json()["skipped"] == []
    second = client.post(f"/api/v1/tenants/{space_id}/org-units/{unit}/role-assignments", headers=owner, json={"role_id": role_id})
    assert second.json()["assigned"] == [] and len(second.json()["skipped"]) == 1
    assert client.post(f"/api/v1/tenants/{space_id}/leave", headers=fay).status_code == 204
    assert _role_in(client, "fay@example.com", space_id)[1] == "revoked"


def test_member_list_shows_who_each_member_is(client):
    space_id, owner = _owner_space(client)
    _register(client, "bea", "bea@example.com")
    added = client.post(f"/api/v1/tenants/{space_id}/members/by-email", headers=owner,
                        json={"email": "bea@example.com", "role": "viewer"})
    assert added.status_code == 201, added.text
    accepted_id = client.get("/api/v1/me/invitations", headers=_token(client, "bea@example.com")).json()[0]["id"]
    client.post(f"/api/v1/me/invitations/{accepted_id}/accept", headers=_token(client, "bea@example.com"))
    members = client.get(f"/api/v1/tenants/{space_id}/members", headers=owner)
    assert members.status_code == 200, members.text
    by_email = {m["email"]: m for m in members.json()}
    assert by_email["owner@acme.example"]["username"] == "owner-acme"
    assert by_email["bea@example.com"]["username"] == "bea"
    assert by_email["bea@example.com"]["role"] == "viewer"


def _share_link(client, space_id, owner, role="viewer", days=7):
    created = client.post(f"/api/v1/tenants/{space_id}/invite-links", headers=owner,
                          json={"role": role, "expires_in_days": days})
    assert created.status_code == 201, created.text
    return created.json()


def _token_of(invite_url):
    return invite_url.split("token=", 1)[1]


def test_share_link_lets_signed_in_people_join_with_the_link_role(client):
    space_id, owner = _owner_space(client)
    link = _share_link(client, space_id, owner, role="contributor")
    assert link["is_share_link"] is True and link["role"] == "contributor" and link["accepted_count"] == 0
    listed = [row for row in client.get(f"/api/v1/tenants/{space_id}/invitations", headers=owner).json()
              if row.get("is_share_link")]
    assert [row["invite_url"] for row in listed] == [link["invite_url"]]

    _register(client, "cyra", "cy@example.com")
    cy = _token(client, "cy@example.com")
    joined = client.post("/api/v1/me/invitations/accept-by-token", headers=cy,
                         json={"token": _token_of(link["invite_url"])})
    assert joined.status_code == 200, joined.text
    assert joined.json()["membership"]["role"] == "contributor"
    assert joined.json()["tenant_name"] == "Acme"
    assert _role_in(client, "cy@example.com", space_id) == ("contributor", "active", "invitation")

    # Using the same link again changes nothing and is not counted twice.
    again = client.post("/api/v1/me/invitations/accept-by-token", headers=cy,
                        json={"token": _token_of(link["invite_url"])})
    assert again.status_code == 200 and again.json()["membership"]["role"] == "contributor"
    count = [row for row in client.get(f"/api/v1/tenants/{space_id}/invitations", headers=owner).json()
             if row.get("is_share_link")][0]["accepted_count"]
    assert count == 1


def test_existing_member_keeps_their_role_when_using_a_share_link(client):
    space_id, owner = _owner_space(client)
    _register(client, "dan", "dan@example.com")
    client.post(f"/api/v1/tenants/{space_id}/members/by-email", headers=owner,
                json={"email": "dan@example.com", "role": "admin"})
    dan = _token(client, "dan@example.com")
    client.post("/api/v1/me/invitations/" + client.get("/api/v1/me/invitations", headers=dan).json()[0]["id"]
                + "/accept", headers=dan)
    link = _share_link(client, space_id, owner, role="viewer")
    result = client.post("/api/v1/me/invitations/accept-by-token", headers=dan,
                         json={"token": _token_of(link["invite_url"])})
    assert result.status_code == 200
    assert _role_in(client, "dan@example.com", space_id)[0] == "admin"


def test_revoked_or_expired_or_unknown_links_answer_not_found(client):
    from datetime import timedelta

    from nexus_core.platform import utc_now
    from nexus_platform.persistence.models import SpaceInviteLinkRecord

    space_id, owner = _owner_space(client)
    revoked = _share_link(client, space_id, owner)
    expired = _share_link(client, space_id, owner)
    client.delete(f"/api/v1/tenants/{space_id}/invitations/{revoked['id']}", headers=owner)
    with client.factory() as db, db.begin():
        row = db.get(SpaceInviteLinkRecord, UUID(expired["id"]))
        row.expires_at = utc_now() - timedelta(minutes=1)

    _register(client, "eve", "eve@example.com")
    eve = _token(client, "eve@example.com")
    for link in (revoked, expired):
        response = client.post("/api/v1/me/invitations/accept-by-token", headers=eve,
                               json={"token": _token_of(link["invite_url"])})
        assert response.status_code == 404, response.text
    unknown = client.post("/api/v1/me/invitations/accept-by-token", headers=eve, json={"token": "not-a-link"})
    assert unknown.status_code == 404
    listed = [row for row in client.get(f"/api/v1/tenants/{space_id}/invitations", headers=owner).json()
              if row.get("is_share_link")]
    assert listed == []


def test_share_links_work_in_every_enterprise_and_need_a_valid_expiry(client):
    _register(client, "fay", "fay@example.com")
    fay = _token(client, "fay@example.com")
    own = client.get("/api/v1/auth/me", headers=fay).json()["data"]["memberships"][0]["id"]
    # A one-member enterprise is an ordinary enterprise (openspec 2026-11-11 decision 1).
    assert client.post(f"/api/v1/tenants/{own}/invite-links", headers=fay, json={"role": "viewer"}).status_code == 201

    space_id, owner = _owner_space(client)
    too_long = client.post(f"/api/v1/tenants/{space_id}/invite-links", headers=owner,
                           json={"role": "viewer", "expires_in_days": 31})
    assert too_long.status_code == 422
    owner_role = client.post(f"/api/v1/tenants/{space_id}/invite-links", headers=owner, json={"role": "owner"})
    assert owner_role.status_code == 422
