"""Sharing enterprise agents with shared spaces (openspec 2026-11-03, section 4). Effective level is the minimum
of the share level, the member space's role in the shared space and the caller's own cap.
Running shared agents is not covered: it needs a cross-space model decision."""
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


def _agent(client, headers, space, name="Helper"):
    profile = client.post(f"/api/v1/tenants/{space}/model-profiles", headers=headers,
                          json={"name": "Model", "provider": "demo", "model_name": "demo-model", "options": {}})
    assert profile.status_code == 201, profile.text
    created = client.post(f"/api/v1/tenants/{space}/agents", headers=headers, json={
        "name": name, "runtime_type": "native", "instructions": "Be precise",
        "model_profile_version_id": profile.json()["current_version"]["id"],
    })
    assert created.status_code == 201, created.text
    return created.json()["id"]


def _join_as(client, shared, code, headers, space, role):
    """Join a shared space, then ask for `role`; the shared space's admin approves."""
    assert client.post("/api/v1/shared-spaces/join", json={"invite_code": code},
                       headers=_as(headers, space)).status_code == 200
    if role != "viewer":
        assert client.post(f"/api/v1/shared-spaces/{shared}/request-upgrade", json={"requested_role": role},
                           headers=_as(headers, space)).status_code == 201


def _approve_all(client, shared, owner_headers):
    for row in client.get(f"/api/v1/shared-spaces/{shared}/join-requests", headers=owner_headers).json():
        client.post(f"/api/v1/shared-spaces/{shared}/join-requests/{row['id']}/approve", json={},
                    headers=owner_headers)


def _world(client, bea_role="editor"):
    """Acme (agent owner) and Beta (recipient) meet in one shared space; Beta's space has role `bea_role`."""
    ann, acme = _register(client, "ann", "enterprise", "Acme", "acme-shr")
    bea, beta = _register(client, "bea", "enterprise", "Beta", "beta-shr")
    # Sharing with another enterprise is off by default (openspec 2026-11-11-enterprise-saas decision 4).
    for headers, space in ((ann, acme), (bea, beta)):
        allowed = client.patch(f"/api/v1/tenants/{space}/admin/policy", json={"external_sharing": True},
                               headers=_as(headers, space))
        assert allowed.status_code == 200, allowed.text
    shared = client.post("/api/v1/shared-spaces", json={"name": "Alliance"}, headers=_as(ann, acme)).json()["id"]
    code = client.post(f"/api/v1/shared-spaces/{shared}/invite-code", headers=_as(ann, acme)).json()["invite_code"]
    _join_as(client, shared, code, bea, beta, bea_role)
    _approve_all(client, shared, _as(ann, acme))
    agent = _agent(client, _as(ann, acme), acme)
    return {"ann": ann, "acme": acme, "bea": bea, "beta": beta, "shared": shared, "agent": agent}


def test_share_level_is_capped_by_the_recipient_space_role(client):
    w = _world(client, bea_role="editor")
    shared = client.post(f"/api/v1/tenants/{w['acme']}/agents/{w['agent']}/shares", headers=_as(w["ann"], w["acme"]),
                         json={"shared_space_id": w["shared"], "level": "admin"})
    assert shared.status_code == 201, shared.text
    listed = client.get(f"/api/v1/tenants/{w['beta']}/shared-agents", headers=_as(w["bea"], w["beta"])).json()
    assert [(a["name"], a["level"]) for a in listed] == [("Helper", "editor")]
    assert "edit" in listed[0]["permissions"] and "publish" not in listed[0]["permissions"]
    assert listed[0]["owner_tenant_name"] == "Acme"


def test_viewer_share_gives_view_and_run_only(client):
    w = _world(client, bea_role="admin")
    client.post(f"/api/v1/tenants/{w['acme']}/agents/{w['agent']}/shares", headers=_as(w["ann"], w["acme"]),
                json={"shared_space_id": w["shared"], "level": "viewer"})
    got = client.get(f"/api/v1/tenants/{w['beta']}/shared-agents/{w['agent']}", headers=_as(w["bea"], w["beta"]))
    assert got.status_code == 200 and got.json()["level"] == "viewer"
    assert sorted(got.json()["permissions"]) == ["run", "view"]


def test_contributor_in_recipient_space_is_capped_to_editor(client):
    w = _world(client, bea_role="admin")
    client.post(f"/api/v1/tenants/{w['acme']}/agents/{w['agent']}/shares", headers=_as(w["ann"], w["acme"]),
                json={"shared_space_id": w["shared"], "level": "admin"})
    cara, _ = _register(client, "cara", "personal")
    invited = client.post(f"/api/v1/tenants/{w['beta']}/members/by-email", headers=_as(w["bea"], w["beta"]),
                          json={"email": "cara@example.com", "role": "contributor"})
    assert invited.status_code == 201, invited.text
    inv_id = client.get("/api/v1/me/invitations", headers=cara).json()[0]["id"]
    client.post(f"/api/v1/me/invitations/{inv_id}/accept", headers=cara)
    level = client.get(f"/api/v1/tenants/{w['beta']}/shared-agents/{w['agent']}", headers=_as(cara, w["beta"])).json()
    assert level["level"] == "editor"


def test_outsiders_and_unshared_agents_are_not_found(client):
    w = _world(client)
    outsider, outsider_space = _register(client, "olga", "enterprise", "Other", "other-shr")
    assert client.get(f"/api/v1/tenants/{outsider_space}/shared-agents",
                      headers=_as(outsider, outsider_space)).json() == []
    assert client.get(f"/api/v1/tenants/{w['beta']}/shared-agents/{w['agent']}",
                      headers=_as(w["bea"], w["beta"])).status_code == 404
    shared_before = client.post(f"/api/v1/tenants/{w['acme']}/agents/{w['agent']}/shares",
                                headers=_as(w["ann"], w["acme"]), json={"shared_space_id": w["shared"], "level": "viewer"})
    assert shared_before.status_code == 201


def test_only_the_owning_space_manages_shares_and_it_must_be_a_member(client):
    w = _world(client)
    # Bea acts for Beta, which is not the owner of the agent: not a member of Acme, so not found.
    attempt = client.post(f"/api/v1/tenants/{w['acme']}/agents/{w['agent']}/shares", headers=_as(w["bea"], w["beta"]),
                          json={"shared_space_id": w["shared"], "level": "viewer"})
    assert attempt.status_code == 404
    # Acme's owner cannot share into a shared space Acme does not belong to.
    other, other_space = _register(client, "oscar", "enterprise", "Third", "third-shr")
    foreign = client.post("/api/v1/shared-spaces", json={"name": "Foreign"}, headers=_as(other, other_space)).json()["id"]
    refused = client.post(f"/api/v1/tenants/{w['acme']}/agents/{w['agent']}/shares", headers=_as(w["ann"], w["acme"]),
                          json={"shared_space_id": foreign, "level": "viewer"})
    assert refused.status_code == 403


def test_unshare_removes_access_and_outside_enterprises_are_refused(client):
    w = _world(client)
    client.post(f"/api/v1/tenants/{w['acme']}/agents/{w['agent']}/shares", headers=_as(w["ann"], w["acme"]),
                json={"shared_space_id": w["shared"], "level": "editor"})
    assert client.get(f"/api/v1/tenants/{w['beta']}/shared-agents", headers=_as(w["bea"], w["beta"])).json()
    removed = client.delete(f"/api/v1/tenants/{w['acme']}/agents/{w['agent']}/shares/{w['shared']}",
                            headers=_as(w["ann"], w["acme"]))
    assert removed.status_code == 204
    assert client.get(f"/api/v1/tenants/{w['beta']}/shared-agents", headers=_as(w["bea"], w["beta"])).json() == []

    # Registration now always creates an enterprise; one that has not joined the shared space cannot share into it.
    solo, solo_space = _register(client, "solo")
    solo_agent = _agent(client, _as(solo, solo_space), solo_space, name="Mine")
    refused = client.post(f"/api/v1/tenants/{solo_space}/agents/{solo_agent}/shares", headers=_as(solo, solo_space),
                          json={"shared_space_id": w["shared"], "level": "viewer"})
    assert refused.status_code == 403
