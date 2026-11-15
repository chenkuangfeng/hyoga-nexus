"""Enterprise organization tree (机构管理): one tree per enterprise, positions of active members, primary node rule.

Covers openspec 2026-11-03-enterprise-personal-spaces section 2: trees belong to one enterprise, positions
need `org:manage`, only active members can be placed, and positions never grant access.
"""
import pytest
from nexus_core.platform import Principal, TenantRole
from nexus_platform.errors import Conflict, Forbidden, NotFound
from nexus_platform.identity.service import resolve_user
from nexus_platform.orgs import service as orgs
from nexus_platform.persistence.models import MembershipRecord, UserOrgUnitRecord
from nexus_platform.tenants.service import add_member, create_tenant, remove_member
from test_platform import database  # noqa: F401  (fixture)

OWNER = Principal(id="org-owner", issuer="test")
VIEWER = Principal(id="org-viewer", issuer="test")
PERSON = Principal(id="org-person", issuer="test")
OUTSIDER = Principal(id="org-outsider", issuer="test")


def _uid(factory, principal):
    with factory() as db, db.begin():
        return resolve_user(db, principal).id


@pytest.fixture
def enterprise(database):
    """An enterprise owned by OWNER, with a VIEWER (no org:manage) and a PERSON who is a contributor."""
    with database() as db:
        tid = create_tenant(db, OWNER, "Acme").id
    with database() as db:
        add_member(db, OWNER, tid, VIEWER, TenantRole.VIEWER)
    with database() as db:
        add_member(db, OWNER, tid, PERSON, TenantRole.CONTRIBUTOR)
    return database, tid


def test_root_is_created_once_and_children_count_active_members(enterprise):
    factory, tid = enterprise
    with factory() as db:
        root_id = orgs.create_unit(db, OWNER, tid, "Acme Group").id
    with factory() as db:
        with pytest.raises(Conflict):
            orgs.create_unit(db, OWNER, tid, "Second root")
    with factory() as db:
        sub = orgs.create_unit(db, OWNER, tid, "R&D", parent_id=root_id).id
    with factory() as db:
        orgs.assign_member(db, OWNER, tid, sub, _uid(factory, PERSON))
    with factory() as db:
        tree = {n["name"]: n for n in orgs.get_tree(db, OWNER, tid)}
        assert tree["R&D"]["member_count"] == 1
        assert tree["Acme Group"]["member_count"] == 0
        assert tree["Acme Group"]["source"] == "manual"


def test_viewer_without_org_manage_is_forbidden(enterprise):
    factory, tid = enterprise
    with factory() as db:
        with pytest.raises(Forbidden):
            orgs.create_unit(db, VIEWER, tid, "Nope")


def test_only_active_members_can_be_placed_and_only_in_own_enterprise(enterprise):
    factory, tid = enterprise
    with factory() as db:
        root_id = orgs.create_unit(db, OWNER, tid, "Root").id
    with factory() as db:
        with pytest.raises(NotFound):
            orgs.assign_member(db, OWNER, tid, root_id, _uid(factory, OUTSIDER))
    with factory() as db:
        other = create_tenant(db, OUTSIDER, "Other").id
    with factory() as db:
        other_root = orgs.create_unit(db, OUTSIDER, other, "Other root").id
    with factory() as db:
        with pytest.raises(NotFound):
            orgs.assign_member(db, OWNER, tid, other_root, _uid(factory, PERSON))


def test_primary_node_is_unique_per_enterprise(enterprise):
    factory, tid = enterprise
    with factory() as db:
        root_id = orgs.create_unit(db, OWNER, tid, "Root").id
    with factory() as db:
        a = orgs.create_unit(db, OWNER, tid, "A", parent_id=root_id).id
        b = orgs.create_unit(db, OWNER, tid, "B", parent_id=root_id).id
    person = _uid(factory, PERSON)
    with factory() as db:
        orgs.assign_member(db, OWNER, tid, a, person)
    with factory() as db:
        orgs.assign_member(db, OWNER, tid, b, person, is_primary=True)
    with factory() as db:
        rows = {r.unit_id: r.is_primary for r in db.query(UserOrgUnitRecord).filter_by(user_id=person).all()}
        assert rows == {a: False, b: True}
    with factory() as db:
        # b is primary and a is another node, so b cannot be removed until another primary is chosen.
        with pytest.raises(Conflict):
            orgs.unassign_member(db, OWNER, tid, b, person)
    with factory() as db:
        orgs.unassign_member(db, OWNER, tid, a, person)


def test_move_rejects_cycles_and_root_moves(enterprise):
    factory, tid = enterprise
    with factory() as db:
        root_id = orgs.create_unit(db, OWNER, tid, "Root").id
    with factory() as db:
        parent = orgs.create_unit(db, OWNER, tid, "Parent", parent_id=root_id).id
    with factory() as db:
        child = orgs.create_unit(db, OWNER, tid, "Child", parent_id=parent).id
    with factory() as db:
        with pytest.raises(Conflict):
            orgs.update_unit(db, OWNER, tid, parent, parent_id=child)
    with factory() as db:
        with pytest.raises(Conflict):
            orgs.update_unit(db, OWNER, tid, root_id, parent_id=child)


def test_disabled_node_cannot_receive_members_and_delete_needs_empty_node(enterprise):
    factory, tid = enterprise
    with factory() as db:
        root_id = orgs.create_unit(db, OWNER, tid, "Root").id
    with factory() as db:
        leaf = orgs.create_unit(db, OWNER, tid, "Leaf", parent_id=root_id).id
    with factory() as db:
        orgs.update_unit(db, OWNER, tid, leaf, status="disabled")
    with factory() as db:
        with pytest.raises(Conflict):
            orgs.assign_member(db, OWNER, tid, leaf, _uid(factory, PERSON))
    with factory() as db:
        orgs.update_unit(db, OWNER, tid, leaf, status="active")
    with factory() as db:
        orgs.assign_member(db, OWNER, tid, leaf, _uid(factory, PERSON))
    with factory() as db:
        with pytest.raises(Conflict):
            orgs.delete_unit(db, OWNER, tid, leaf)
    with factory() as db:
        orgs.unassign_member(db, OWNER, tid, leaf, _uid(factory, PERSON))
    with factory() as db:
        orgs.delete_unit(db, OWNER, tid, leaf)
    with factory() as db:
        with pytest.raises(Conflict):
            orgs.delete_unit(db, OWNER, tid, root_id)


def test_revoked_members_keep_position_but_are_not_counted(enterprise):
    factory, tid = enterprise
    with factory() as db:
        root_id = orgs.create_unit(db, OWNER, tid, "Root").id
    person = _uid(factory, PERSON)
    with factory() as db:
        orgs.assign_member(db, OWNER, tid, root_id, person)
    with factory() as db:
        remove_member(db, OWNER, tid, person)
    with factory() as db:
        assert orgs.get_tree(db, OWNER, tid)[0]["member_count"] == 0
        assert db.get(MembershipRecord, (tid, person)).status == "revoked"
        assert db.get(UserOrgUnitRecord, (tid, person, root_id)) is not None


def test_directory_node_protection_includes_mapped_manual_root(enterprise):
    from nexus_platform.persistence.models import OrgUnitRecord

    factory, tid = enterprise
    with factory() as db:
        root_id = orgs.create_unit(db, OWNER, tid, 'Manual root').id
    with factory() as db, db.begin():
        db.get(OrgUnitRecord, root_id).external_id = '1'
    with factory() as db:
        assert orgs.get_tree(db, OWNER, tid)[0]['sync_managed'] is True
    for changes in ({'name': 'Overwrite'}, {'status': 'disabled'}):
        with factory() as db, pytest.raises(Conflict):
            orgs.update_unit(db, OWNER, tid, root_id, **changes)
    with factory() as db, pytest.raises(Conflict):
        orgs.delete_unit(db, OWNER, tid, root_id)
    with factory() as db:
        child = orgs.create_unit(db, OWNER, tid, 'Local team', parent_id=root_id)
        assert child.source == 'manual'
    with factory() as db:
        orgs.update_unit(db, OWNER, tid, child.id, name='Renamed')


def test_manual_and_directory_contributions_survive_independent_removal(enterprise):
    from nexus_platform.wecom.service import _apply_departments, _place_member

    factory, tid = enterprise
    person = _uid(factory, PERSON)
    with factory() as db, db.begin():
        mapping = _apply_departments(db, tid, [{'id': 1, 'name': 'Root', 'parentid': 0},
                                              {'id': 2, 'name': 'Directory team', 'parentid': 1}])
        unit = mapping['2']
        _place_member(db, tid, person, ['2'])
    with factory() as db, pytest.raises(Conflict):
        orgs.unassign_member(db, OWNER, tid, unit, person)
    with factory() as db:
        assert orgs.assign_member(db, OWNER, tid, unit, person).source == 'mixed'
    with factory() as db:
        orgs.unassign_member(db, OWNER, tid, unit, person)
    with factory() as db, db.begin():
        link = db.get(UserOrgUnitRecord, (tid, person, unit))
        assert (link.source, link.is_primary) == ('wecom', True)
    with factory() as db:
        orgs.assign_member(db, OWNER, tid, unit, person)
    with factory() as db, db.begin():
        _place_member(db, tid, person, [])
        db.flush()
        link = db.get(UserOrgUnitRecord, (tid, person, unit))
        assert (link.source, link.is_primary) == ('manual', True)
        _place_member(db, tid, person, ['2'])
        assert link.source == 'mixed'
    with factory() as db:
        rows = orgs.list_unit_members(db, OWNER, tid, unit)
        assert rows[0]['source'] == 'mixed'
    # An unrelated manual primary remains untouched while directory-only links disappear.
    with factory() as db:
        manual = orgs.create_unit(db, OWNER, tid, 'Local', parent_id=mapping['1']).id
    with factory() as db:
        orgs.assign_member(db, OWNER, tid, manual, person, is_primary=True)
    with factory() as db:
        orgs.unassign_member(db, OWNER, tid, unit, person)
    with factory() as db, db.begin():
        _place_member(db, tid, person, [])
        db.flush()
        assert db.get(UserOrgUnitRecord, (tid, person, unit)) is None
        assert db.get(UserOrgUnitRecord, (tid, person, manual)).is_primary


def test_org_http_reports_sources_and_refuses_directory_overwrite(enterprise):
    from fastapi.testclient import TestClient
    from nexus_api.main import app
    from nexus_api.dependencies.platform import get_database_session, get_principal
    from nexus_platform.persistence.models import OrgUnitRecord

    factory, tid = enterprise
    with factory() as db:
        root = orgs.create_unit(db, OWNER, tid, 'Root').id
    with factory() as db, db.begin():
        db.get(OrgUnitRecord, root).external_id = '1'
    def database_dependency():
        with factory() as db:
            yield db
    old_overrides = dict(app.dependency_overrides)
    app.dependency_overrides[get_database_session] = database_dependency
    app.dependency_overrides[get_principal] = lambda: OWNER
    try:
        client = TestClient(app, raise_server_exceptions=True)
        path = f'/api/v1/tenants/{tid}/admin/org-units'
        tree = client.get(path + '/tree')
        assert tree.status_code == 200
        assert tree.json()[0]['sync_managed'] is True
        assert client.patch(f'{path}/{root}', json={'name': 'Overwrite'}).status_code == 409
        person = str(_uid(factory, PERSON))
        assigned = client.put(f'{path}/{root}/members/{person}', json={})
        assert assigned.status_code == 200
        assert assigned.json()['source'] == 'manual'
        assert client.get(f'{path}/{root}/members').json()[0]['source'] == 'manual'
    finally:
        client.close()
        app.dependency_overrides.clear()
        app.dependency_overrides.update(old_overrides)
