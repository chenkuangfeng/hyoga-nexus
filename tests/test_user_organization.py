"""Organization tree, primary node, space bindings and joining people from a bound subtree."""
import pytest

from nexus_core.platform import Principal, TenantRole
from nexus_platform.errors import Conflict, Forbidden, NotFound
from nexus_platform.identity.service import resolve_user
from nexus_platform.orgs import service as orgs
from nexus_platform.persistence.models import UserRecord
from nexus_platform.tenants.service import add_member, create_tenant
from test_platform import database  # noqa: F401  (fixture)

ADMIN = Principal(id="org-admin", issuer="test")
OWNER = Principal(id="space-owner", issuer="test")
MEMBER = Principal(id="space-member", issuer="test")
PERSON = Principal(id="person-a", issuer="test")
PERSON_B = Principal(id="person-b", issuer="test")
OUTSIDER = Principal(id="outsider", issuer="test")


def _uid(factory, principal):
    with factory() as db, db.begin():
        return resolve_user(db, principal).id


def _make_admin(factory, principal):
    uid = _uid(factory, principal)
    with factory() as db, db.begin():
        db.get(UserRecord, uid).is_platform_admin = True
    return uid


def _space(factory):
    with factory() as db:
        tid = create_tenant(db, OWNER, "Group Space").id
    with factory() as db:
        add_member(db, OWNER, tid, MEMBER, TenantRole.MEMBER)
    return tid


def test_tree_allows_any_depth_and_rejects_moving_under_own_subtree(database):
    _make_admin(database, ADMIN)
    with database() as db:
        root = orgs.create_organization(db, ADMIN, "Group")
        root_id = root.id
    parent = root_id
    chain = []
    for level in range(12):  # no depth limit
        with database() as db:
            node = orgs.create_unit(db, ADMIN, parent, f"level-{level}")
            chain.append(node.id)
            parent = node.id
    with database() as db:
        with pytest.raises(Conflict):
            orgs.update_unit(db, ADMIN, root_id, parent_id=chain[-1])  # root cannot move
    with database() as db:
        with pytest.raises(Conflict):
            orgs.update_unit(db, ADMIN, chain[2], parent_id=chain[5])  # into its own subtree
    with database() as db:
        moved = orgs.update_unit(db, ADMIN, chain[-1], parent_id=root_id)
        assert moved.parent_id == root_id


def test_sibling_names_are_unique_and_roots_too(database):
    _make_admin(database, ADMIN)
    with database() as db:
        root = orgs.create_organization(db, ADMIN, "Group")
        root_id = root.id
    with database() as db:
        orgs.create_unit(db, ADMIN, root_id, "Sub")
    with database() as db:
        with pytest.raises(Conflict):
            orgs.create_unit(db, ADMIN, root_id, "Sub")
    with database() as db:
        with pytest.raises(Conflict):
            orgs.create_organization(db, ADMIN, "Group")


def test_non_platform_admin_cannot_manage_organizations(database):
    with database() as db:
        with pytest.raises(Forbidden):
            orgs.create_organization(db, OWNER, "Nope")


def test_user_has_one_primary_node(database):
    _make_admin(database, ADMIN)
    uid = _uid(database, PERSON)
    with database() as db:
        root_id = orgs.create_organization(db, ADMIN, "Group").id
    with database() as db:
        first = orgs.create_unit(db, ADMIN, root_id, "Sales").id
    with database() as db:
        second = orgs.create_unit(db, ADMIN, root_id, "Support").id
    with database() as db:
        orgs.assign_member(db, ADMIN, first, uid)  # first node becomes primary automatically
    with database() as db:
        orgs.assign_member(db, ADMIN, second, uid)
    with database() as db:
        orgs.assign_member(db, ADMIN, second, uid, is_primary=True)
    from nexus_platform.persistence.models import UserOrgUnitRecord
    from sqlalchemy import select
    with database() as db:
        rows = {row.unit_id: row.is_primary for row in db.scalars(
            select(UserOrgUnitRecord).where(UserOrgUnitRecord.user_id == uid))}
        assert rows == {first: False, second: True}
    with database() as db:
        with pytest.raises(Conflict):
            orgs.unassign_member(db, ADMIN, second, uid)  # primary with another node left
    with database() as db:
        orgs.unassign_member(db, ADMIN, first, uid)
    with database() as db:
        orgs.unassign_member(db, ADMIN, second, uid)  # last node may go


def test_delete_requires_empty_node(database):
    _make_admin(database, ADMIN)
    uid = _uid(database, PERSON)
    with database() as db:
        root_id = orgs.create_organization(db, ADMIN, "Group").id
    with database() as db:
        sub = orgs.create_unit(db, ADMIN, root_id, "Sub").id
    with database() as db:
        orgs.create_unit(db, ADMIN, sub, "Dept")
    with database() as db:
        with pytest.raises(Conflict):
            orgs.delete_unit(db, ADMIN, sub)
    with database() as db:
        orgs.assign_member(db, ADMIN, root_id, uid)
    with database() as db:
        with pytest.raises(Conflict):
            orgs.delete_unit(db, ADMIN, root_id)


def test_space_binds_group_and_subsidiary_and_sees_distinct_people(database):
    _make_admin(database, ADMIN)
    tid = _space(database)
    a, b = _uid(database, PERSON), _uid(database, PERSON_B)
    with database() as db:
        root_id = orgs.create_organization(db, ADMIN, "Group").id
    with database() as db:
        sub = orgs.create_unit(db, ADMIN, root_id, "Subsidiary").id
    with database() as db:
        dept = orgs.create_unit(db, ADMIN, sub, "Dept").id
    with database() as db:
        orgs.assign_member(db, ADMIN, dept, a)
    with database() as db:
        orgs.assign_member(db, ADMIN, sub, a)  # same person in two nodes of the subtree
    with database() as db:
        orgs.assign_member(db, ADMIN, sub, b)
    with database() as db:
        orgs.bind_space(db, ADMIN, tid, root_id)
    with database() as db:
        orgs.bind_space(db, ADMIN, tid, sub)  # group plus a subsidiary
    with database() as db:
        with pytest.raises(Conflict):
            orgs.bind_space(db, ADMIN, tid, sub)
    with database() as db:
        view = orgs.space_organization(db, MEMBER, tid)
    assert {bind["unit_name"] for bind in view["bindings"]} == {"Group", "Subsidiary"}
    assert sorted(person["user_id"] for person in view["people"]) == sorted([a, b])
    with database() as db:
        with pytest.raises(NotFound):
            orgs.space_organization(db, OUTSIDER, tid)


def test_owner_adds_people_from_bound_subtree_only(database):
    _make_admin(database, ADMIN)
    tid = _space(database)
    inside, outside = _uid(database, PERSON), _uid(database, PERSON_B)
    with database() as db:
        root_id = orgs.create_organization(db, ADMIN, "Group").id
    with database() as db:
        sub = orgs.create_unit(db, ADMIN, root_id, "Subsidiary").id
    with database() as db:
        orgs.assign_member(db, ADMIN, sub, inside)
    with database() as db:
        orgs.bind_space(db, ADMIN, tid, sub)
    with database() as db:
        result = orgs.add_members_from_organization(db, OWNER, tid, [inside], TenantRole.MEMBER)
    assert result == {"added": [inside], "skipped": []}
    with database() as db:
        again = orgs.add_members_from_organization(db, OWNER, tid, [inside], TenantRole.MEMBER)
    assert again == {"added": [], "skipped": [inside]}
    with database() as db:
        with pytest.raises(NotFound):
            orgs.add_members_from_organization(db, OWNER, tid, [outside], TenantRole.MEMBER)
    with database() as db:
        with pytest.raises(Forbidden):  # members:manage is required
            orgs.add_members_from_organization(db, MEMBER, tid, [inside], TenantRole.MEMBER)
    with database() as db:
        with pytest.raises(Forbidden):  # owners are not created this way
            orgs.add_members_from_organization(db, OWNER, tid, [inside], TenantRole.OWNER)


def test_unbinding_is_allowed_to_owner_and_refused_to_plain_members(database):
    _make_admin(database, ADMIN)
    tid = _space(database)
    with database() as db:
        root_id = orgs.create_organization(db, ADMIN, "Group").id
    with database() as db:
        orgs.bind_space(db, ADMIN, tid, root_id)
    with database() as db:
        with pytest.raises(Forbidden):
            orgs.unbind_space(db, MEMBER, tid, root_id)
    with database() as db:
        orgs.unbind_space(db, OWNER, tid, root_id)
    with database() as db:
        with pytest.raises(NotFound):
            orgs.unbind_space(db, OWNER, tid, root_id)


def test_disabled_node_cannot_receive_people_or_bindings(database):
    _make_admin(database, ADMIN)
    tid = _space(database)
    uid = _uid(database, PERSON)
    with database() as db:
        root_id = orgs.create_organization(db, ADMIN, "Group").id
    with database() as db:
        sub = orgs.create_unit(db, ADMIN, root_id, "Old").id
    with database() as db:
        orgs.update_unit(db, ADMIN, sub, status="disabled")
    with database() as db:
        with pytest.raises(Conflict):
            orgs.assign_member(db, ADMIN, sub, uid)
    with database() as db:
        with pytest.raises(Conflict):
            orgs.bind_space(db, ADMIN, tid, sub)


def test_organization_api_enforces_platform_admin_and_space_view(database):
    """HTTP layer: admin-only tree writes, member-only space view, and join-from-organization."""
    from fastapi.testclient import TestClient

    from nexus_api.dependencies.platform import get_database_session, get_principal
    from nexus_api.main import app

    _make_admin(database, ADMIN)
    inside = _uid(database, PERSON)
    tid = _space(database)
    app.state.session_factory = database

    def override_db():
        with database() as db:
            yield db

    current = {"principal": ADMIN}
    app.dependency_overrides[get_database_session] = override_db
    app.dependency_overrides[get_principal] = lambda: current["principal"]
    try:
        with TestClient(app) as client:
            root = client.post("/api/v1/orgs", json={"name": "Group HTTP"})
            assert root.status_code == 201, root.text
            root_id = root.json()["id"]
            sub = client.post("/api/v1/org-units", json={"parent_id": root_id, "name": "Sub"}).json()["id"]
            assert client.put(f"/api/v1/org-units/{sub}/members/{inside}", json={"is_primary": True}).status_code == 200
            assert client.put(f"/api/v1/tenants/{tid}/organization-bindings/{sub}").status_code == 204

            current["principal"] = MEMBER
            assert client.post("/api/v1/orgs", json={"name": "Hack"}).status_code == 403
            view = client.get(f"/api/v1/tenants/{tid}/organization")
            assert view.status_code == 200, view.text
            assert [p["user_id"] for p in view.json()["people"]] == [str(inside)]
            assert client.post(f"/api/v1/tenants/{tid}/members/from-organization",
                               json={"user_ids": [str(inside)]}).status_code == 403

            current["principal"] = OWNER
            joined = client.post(f"/api/v1/tenants/{tid}/members/from-organization",
                                 json={"user_ids": [str(inside)], "role": "member"})
            assert joined.status_code == 200, joined.text
            assert joined.json() == {"added": [str(inside)], "skipped": []}

            current["principal"] = OUTSIDER
            assert client.get(f"/api/v1/tenants/{tid}/organization").status_code == 404
    finally:
        app.dependency_overrides.clear()
        app.state.session_factory = None


def test_user_directory_is_platform_admin_only(database):
    _make_admin(database, ADMIN)
    _uid(database, PERSON)
    with database() as db:
        names = {row["user_id"]: row for row in orgs.list_users(db, ADMIN)}
    assert "person-a" in {row["display_name"] for row in names.values()}
    with database() as db:
        assert [r["display_name"] for r in orgs.list_users(db, ADMIN, "person-a")] == ["person-a"]
    with database() as db:
        with pytest.raises(Forbidden):
            orgs.list_users(db, OWNER)


def test_unit_bindings_lists_spaces_for_admin_only(database):
    _make_admin(database, ADMIN)
    tid = _space(database)
    with database() as db:
        root_id = orgs.create_organization(db, ADMIN, "Group Bindings").id
    with database() as db:
        orgs.bind_space(db, ADMIN, tid, root_id)
    with database() as db:
        assert [row["tenant_id"] for row in orgs.unit_bindings(db, ADMIN, root_id)] == [tid]
    with database() as db:
        with pytest.raises(Forbidden):
            orgs.unit_bindings(db, OWNER, root_id)


def test_platform_admin_flag_is_set_by_operator_for_password_accounts(database):
    from nexus_platform.auth.accounts import create_owner_account
    from nexus_platform.orgs.service import set_platform_admin
    from nexus_platform.persistence.models import UserRecord as Users
    with database() as db:
        create_owner_account(db, tenant_name="Ops", username="ops-owner", display_name="Ops", password="correct-horse-1")
    with database() as db:
        user = set_platform_admin(db, username="ops-owner", enabled=True)
        assert user.is_platform_admin is True
    with database() as db:
        assert db.get(Users, user.id).is_platform_admin is True
    with database() as db:
        set_platform_admin(db, username="ops-owner", enabled=False)
    with database() as db:
        with pytest.raises(NotFound):
            set_platform_admin(db, username="nobody-here", enabled=True)
