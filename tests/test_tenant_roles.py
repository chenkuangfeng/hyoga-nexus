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
