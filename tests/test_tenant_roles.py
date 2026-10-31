"""Tenant roles: union of grants, escalation guard, tenant isolation and API enforcement."""
import pytest
from fastapi.testclient import TestClient

from nexus_api.dependencies.platform import get_database_session, get_principal
from nexus_api.main import app
from nexus_core.platform import Principal, TenantRole
from nexus_platform.errors import Conflict, Forbidden, InvalidConfiguration, NotFound
from nexus_platform.tenants import roles
from nexus_platform.tenants.service import add_member, create_tenant
from test_platform import database  # noqa: F401  (fixture)

OWNER = Principal(id="owner", issuer="test")
MEMBER = Principal(id="member", issuer="test")
OTHER = Principal(id="other", issuer="test")


def _uid(factory, principal):
    """Resolve a principal in its own session so service calls start with no open transaction."""
    from nexus_platform.identity.service import resolve_user
    with factory() as db, db.begin():
        return resolve_user(db, principal).id


def _setup(factory):
    with factory() as db:
        tenant = create_tenant(db, OWNER, "Roles")
        tid = tenant.id
    with factory() as db:
        add_member(db, OWNER, tid, MEMBER, TenantRole.MEMBER)
    with factory() as db:
        add_member(db, OWNER, tid, OTHER, TenantRole.MEMBER)
    return tid


def test_member_gets_union_of_assigned_roles(database):
    tid = _setup(database)
    member = _uid(database, MEMBER)
    with database() as db:
        reader = roles.create_role(db, OWNER, tid, "reader", ["agents"], ["agents:read"])
        runner = roles.create_role(db, OWNER, tid, "runner", ["chat"], ["sessions:write", "runs:write"])
        roles.assign_role(db, OWNER, tid, member, reader.id)
        roles.assign_role(db, OWNER, tid, member, runner.id)
    with database() as db:
        permissions = roles.my_permissions(db, MEMBER, tid)
        assert permissions.menus == {"agents", "chat"}
        assert permissions.apis == {"agents:read", "sessions:write", "runs:write"}


def test_unassigned_member_has_no_access_and_removed_role_is_dropped(database):
    tid = _setup(database)
    member = _uid(database, MEMBER)
    with database() as db:
        assert roles.effective_permissions(db, tid, member).apis == frozenset()
    with database() as db:
        role = roles.create_role(db, OWNER, tid, "auditor", ["audit"], ["audit:read"])
        roles.assign_role(db, OWNER, tid, member, role.id)
        roles.unassign_role(db, OWNER, tid, member, role.id)
    with database() as db:
        assert roles.effective_permissions(db, tid, member).apis == frozenset()


def test_owner_full_access_and_non_manager_cannot_create_roles(database):
    tid = _setup(database)
    with database() as db:
        assert roles.my_permissions(db, OWNER, tid).apis == roles.FULL_ACCESS.apis
        with pytest.raises(Forbidden):
            roles.create_role(db, MEMBER, tid, "nope", [], [])


def test_role_manager_cannot_grant_permissions_it_does_not_hold(database):
    tid = _setup(database)
    member = _uid(database, MEMBER)
    with database() as db:
        manager = roles.create_role(db, OWNER, tid, "manager", ["roles", "agents"], ["roles:manage", "agents:read"])
        roles.assign_role(db, OWNER, tid, member, manager.id)
    with database() as db:
        with pytest.raises(Forbidden):
            roles.create_role(db, MEMBER, tid, "escalated", ["models"], ["models:manage"])
        created = roles.create_role(db, MEMBER, tid, "readers", ["agents"], ["agents:read"])
        assert created.name == "readers"


def test_grants_are_validated_against_catalog_and_names_are_unique(database):
    tid = _setup(database)
    with database() as db:
        with pytest.raises(InvalidConfiguration):
            roles.create_role(db, OWNER, tid, "bad", ["secret-menu"], [])
    with database() as db:
        roles.create_role(db, OWNER, tid, "dup", [], [])
    with database() as db:
        with pytest.raises(Conflict):
            roles.create_role(db, OWNER, tid, "dup", [], [])


def test_assignment_requires_active_member_and_same_tenant(database):
    tid = _setup(database)
    with database() as db:
        other_tenant = create_tenant(db, OWNER, "Elsewhere").id
    with database() as db:
        foreign_role = roles.create_role(db, OWNER, other_tenant, "foreign", [], ["agents:read"])
        with pytest.raises(NotFound):
            roles.update_role_grants(db, OWNER, tid, foreign_role.id, [], [])
    stranger = _uid(database, Principal(id="stranger", issuer="test"))
    with database() as db:
        local = roles.create_role(db, OWNER, tid, "local", [], ["agents:read"])
        with pytest.raises(NotFound):
            roles.assign_role(db, OWNER, tid, stranger, local.id)


def test_roles_api_enforces_manage_permission(database):
    app.state.session_factory = database

    def override_db():
        with database() as db:
            yield db

    current = {"principal": OWNER}
    app.dependency_overrides[get_database_session] = override_db
    app.dependency_overrides[get_principal] = lambda: current["principal"]
    try:
        with TestClient(app) as client:
            tid = client.post("/api/v1/tenants", json={"name": "API roles"}).json()["id"]
            added = client.post(f"/api/v1/tenants/{tid}/members",
                                json={"issuer": "test", "subject": "member", "role": "member"})
            assert added.status_code == 201, added.text
            created = client.post(f"/api/v1/tenants/{tid}/roles",
                                  json={"name": "viewer", "menus": ["agents"], "apis": ["agents:read"]})
            assert created.status_code == 201, created.text
            role_id = created.json()["id"]
            assert client.post(f"/api/v1/tenants/{tid}/roles",
                               json={"name": "x", "apis": ["bogus:perm"]}).status_code == 422
            member_id = added.json()["user_id"]
            assigned = client.put(f"/api/v1/tenants/{tid}/members/{member_id}/roles/{role_id}")
            assert assigned.status_code == 204, assigned.text

            current["principal"] = MEMBER
            mine = client.get(f"/api/v1/tenants/{tid}/me/permissions")
            assert mine.json() == {"menus": ["agents"], "apis": ["agents:read"]}
            assert client.get(f"/api/v1/tenants/{tid}/roles").status_code == 403
            assert client.post(f"/api/v1/tenants/{tid}/roles", json={"name": "y"}).status_code == 403
            assert client.get(f"/api/v1/tenants/{tid}/permission-catalog").status_code == 200
    finally:
        app.dependency_overrides.clear()
        app.state.session_factory = None


# ---- agent-level grants ----------------------------------------------------------------------

from nexus_platform.agents import access as agent_access  # noqa: E402
from nexus_platform.agents.service import update_agent_draft  # noqa: E402
from nexus_platform.authz.catalog import expand_agent_permissions  # noqa: E402
from nexus_platform.errors import InvalidConfiguration as _InvalidConfiguration  # noqa: E402
from nexus_platform.persistence.models import AgentRecord  # noqa: E402
from nexus_platform.sessions.service import create_session  # noqa: E402
from nexus_platform.agents.service import publish_agent  # noqa: E402
from test_platform import create_agent_stack  # noqa: E402


def _grant_agent(factory, owner, tid, agent_id, perms, *, menus=("agents",), apis=("agents:read",)):
    member = _uid(factory, MEMBER)
    with factory() as db:
        role = roles.create_role(db, owner, tid, f"agent-role-{len(perms)}-{'-'.join(perms)}", list(menus), list(apis))
        role_id = role.id
    with factory() as db:
        agent_access.set_agent_grants(db, owner, tid, role_id, agent_id, perms)
    with factory() as db:
        roles.assign_role(db, owner, tid, member, role_id)
    return role_id


def test_agent_permissions_follow_implication_and_visibility(database):
    owner_principal = Principal(id="agent-owner", issuer="test")
    tenant, _, _, agent, _, _ = create_agent_stack(database, owner_principal)
    tid = tenant.id
    with database() as db:
        add_member(db, owner_principal, tid, MEMBER, TenantRole.MEMBER)
    _grant_agent(database, owner_principal, tid, agent.id, ["edit"])
    with database() as db:
        record = db.get(AgentRecord, agent.id)
        granted = agent_access.agent_permissions(db, tid, _uid(database, MEMBER), record)
        assert granted == {"edit", "view"}
        assert "run" not in granted
        assert agent_access.visible_agent_ids(db, tid, _uid(database, MEMBER)) == {agent.id}
    with database() as db:
        with pytest.raises(Forbidden):
            agent_access.require_agent_permission(db, tid, _uid(database, MEMBER), db.get(AgentRecord, agent.id), "run")
    with database() as db:
        assert expand_agent_permissions(["publish"]) == {"publish", "edit", "view"}
        assert expand_agent_permissions(["manage"]) == agent_access.AGENT_PERMISSIONS


def test_agent_without_grant_is_hidden_and_run_requires_run_permission(database):
    owner_principal = Principal(id="agent-owner-2", issuer="test")
    tenant, _, _, agent, version, session = create_agent_stack(database, owner_principal)
    tid = tenant.id
    with database() as db:
        add_member(db, owner_principal, tid, MEMBER, TenantRole.MEMBER)
    member = _uid(database, MEMBER)
    with database() as db:
        assert agent_access.visible_agent_ids(db, tid, member) == set()
        with pytest.raises(NotFound):
            agent_access.require_agent_permission(db, tid, member, db.get(AgentRecord, agent.id), "view")
    _grant_agent(database, owner_principal, tid, agent.id, ["view"])
    with database() as db:
        with pytest.raises(Forbidden):
            create_session(db, MEMBER, tid, agent_version_id=version.id, title="blocked")
    _grant_agent(database, owner_principal, tid, agent.id, ["run"])
    with database() as db:
        created = create_session(db, MEMBER, tid, agent_version_id=version.id, title="allowed")
        assert created.agent_version_id == version.id


def test_edit_and_publish_need_agent_permission_and_manager_cannot_over_grant(database):
    owner_principal = Principal(id="agent-owner-3", issuer="test")
    tenant, profile, model_version, agent, _, _ = create_agent_stack(database, owner_principal)
    tid = tenant.id
    with database() as db:
        add_member(db, owner_principal, tid, MEMBER, TenantRole.MEMBER)
    _grant_agent(database, owner_principal, tid, agent.id, ["view"])
    with database() as db:
        with pytest.raises(Forbidden):
            update_agent_draft(db, MEMBER, tid, agent.id, name="Hacked", description="x",
                               runtime_type="native", instructions="x",
                               model_profile_version_id=model_version.id, budgets={"max_rounds": 1}, bindings=[])
    with database() as db:
        with pytest.raises(Forbidden):
            publish_agent(db, MEMBER, tid, agent.id)
    # A member whose role may only view cannot grant edit on the agent to another role.
    member = _uid(database, MEMBER)
    with database() as db:
        viewer_role = roles.create_role(db, owner_principal, tid, "viewer-manager", ["roles"],
                                        ["roles:manage"])
        roles.assign_role(db, owner_principal, tid, member, viewer_role.id)
    with database() as db:
        target = roles.create_role(db, owner_principal, tid, "target", [], [])
    with database() as db:
        with pytest.raises(Forbidden):
            agent_access.set_agent_grants(db, MEMBER, tid, target.id, agent.id, ["edit"])
    with database() as db:
        with pytest.raises(_InvalidConfiguration):
            agent_access.set_agent_grants(db, owner_principal, tid, target.id, agent.id, ["teleport"])
