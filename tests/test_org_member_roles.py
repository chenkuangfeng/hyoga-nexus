"""Roles given to bound-subtree people: organization-sourced memberships, their activity, and session visibility."""
import pytest
from nexus_core.platform import Principal, TenantRole
from nexus_platform.errors import Forbidden, NotFound
from nexus_platform.identity.service import resolve_user
from nexus_platform.orgs import service as orgs
from nexus_platform.persistence.models import AgentRecord, MembershipRecord, SessionRecord, UserRecord
from nexus_platform.authz.permissions import effective_permissions
from nexus_platform.agents import access as agent_access
from nexus_platform.sessions.service import create_session, get_session_for_user, list_sessions
from nexus_platform.tenants import roles
from nexus_platform.tenants.service import add_member, list_tenants
from test_platform import create_agent_stack, database  # noqa: F401  (fixture)

ADMIN = Principal(id="org-admin-r", issuer="test")
OWNER = Principal(id="role-space-owner", issuer="test")
MANUAL = Principal(id="manual-member", issuer="test")
PERSON = Principal(id="org-person", issuer="test")


def _uid(factory, principal):
    with factory() as db, db.begin():
        return resolve_user(db, principal).id


def _platform_admin(factory):
    uid = _uid(factory, ADMIN)
    with factory() as db, db.begin():
        db.get(UserRecord, uid).is_platform_admin = True


def _bound_space_with_person(factory, tid):
    """Bind the space to a subsidiary and place PERSON inside it. Returns (unit_id, person_id)."""
    _platform_admin(factory)
    person = _uid(factory, PERSON)
    with factory() as db:
        root = orgs.create_organization(db, ADMIN, "Group R").id
    with factory() as db:
        sub = orgs.create_unit(db, ADMIN, root, "Sub R").id
    with factory() as db:
        orgs.assign_member(db, ADMIN, sub, person)
    with factory() as db:
        orgs.bind_space(db, ADMIN, tid, sub)
    return sub, person


def _role_with_agent(factory, tid, agent_id, perms=("view", "run")):
    with factory() as db:
        role_id = roles.create_role(db, OWNER, tid, "agent-user", ["agents"], ["agents:read"]).id
    with factory() as db:
        agent_access.set_agent_grants(db, OWNER, tid, role_id, agent_id, list(perms))
    return role_id


def test_role_from_organization_grants_access_only_while_bound(database):
    owner_principal = OWNER
    tenant, _, _, agent, version, _ = create_agent_stack(database, owner_principal)
    tid = tenant.id
    _sub, person = _bound_space_with_person(database, tid)
    role_id = _role_with_agent(database, tid, agent.id)
    with database() as db:
        result = orgs.add_members_from_organization(db, owner_principal, tid, [person], [role_id])
    assert result == {"added": [person], "skipped": []}
    with database() as db:
        membership = db.get(MembershipRecord, (tid, person))
        assert membership.source == "organization" and membership.role == TenantRole.MEMBER.value
    with database() as db:
        assert [(role, via) for _t, role, via in list_tenants(db, PERSON)] == [(TenantRole.MEMBER.value, True)]
    with database() as db:
        assert "run" in agent_access.agent_permissions(db, tid, person, db.get(AgentRecord, agent.id))
    with database() as db:
        created = create_session(db, PERSON, tid, agent_version_id=version.id, title="from org")
        created_id = created.id
    with database() as db:
        assert db.get(SessionRecord, created_id).org_unit_id is not None

    # Unbinding the space ends the organization access without deleting the membership row.
    with database() as db:
        orgs.unbind_space(db, ADMIN, tid, _sub)
    with database() as db:
        assert list_tenants(db, PERSON) == []
    with database() as db:
        assert effective_permissions(db, tid, person).menus == frozenset()
    with database() as db:
        with pytest.raises(NotFound):
            get_session_for_user(db, PERSON, tid, created_id)
    with database() as db:
        assert db.get(MembershipRecord, (tid, person)) is not None

    with database() as db:
        orgs.bind_space(db, ADMIN, tid, _sub)
    with database() as db:
        assert [(role, via) for _t, role, via in list_tenants(db, PERSON)] == [(TenantRole.MEMBER.value, True)]


def test_revoking_last_role_removes_organization_membership_but_not_manual_ones(database):
    tenant, _, _, agent, _version, _ = create_agent_stack(database, OWNER)
    tid = tenant.id
    _sub, person = _bound_space_with_person(database, tid)
    role_id = _role_with_agent(database, tid, agent.id)
    with database() as db:
        orgs.add_members_from_organization(db, OWNER, tid, [person], [role_id])
    with database() as db:
        roles.unassign_role(db, OWNER, tid, person, role_id)
    with database() as db:
        assert db.get(MembershipRecord, (tid, person)) is None

    manual = _uid(database, MANUAL)
    with database() as db:
        add_member(db, OWNER, tid, MANUAL, TenantRole.MEMBER)
    with database() as db:
        roles.assign_role(db, OWNER, tid, manual, role_id)
    with database() as db:
        roles.unassign_role(db, OWNER, tid, manual, role_id)
    with database() as db:
        assert db.get(MembershipRecord, (tid, manual)).source == "manual"


def test_owner_and_admin_see_every_session_while_members_see_their_own(database):
    tenant, _, _, agent, version, owner_session = create_agent_stack(database, OWNER)
    tid = tenant.id
    _sub, person = _bound_space_with_person(database, tid)
    role_id = _role_with_agent(database, tid, agent.id)
    with database() as db:
        orgs.add_members_from_organization(db, OWNER, tid, [person], [role_id])
    with database() as db:
        add_member(db, OWNER, tid, MANUAL, TenantRole.MEMBER)
    with database() as db:
        org_session = create_session(db, PERSON, tid, agent_version_id=version.id, title="org chat")
        org_id = org_session.id
    with database() as db:
        owner_visible = {row.id for row in list_sessions(db, OWNER, tid)}
    assert {owner_session.id, org_id} <= owner_visible
    with database() as db:
        assert {row.id for row in list_sessions(db, PERSON, tid)} == {org_id}
    with database() as db:
        assert list_sessions(db, MANUAL, tid) == []
        with pytest.raises(NotFound):
            get_session_for_user(db, MANUAL, tid, org_id)
    with database() as db:
        assert get_session_for_user(db, OWNER, tid, org_id).owner_user_id == person


def test_platform_admin_lists_sessions_across_spaces_with_filters(database):
    from nexus_platform.sessions.service import list_sessions_for_platform_admin
    _platform_admin(database)
    tenant, _, _, agent, version, owner_session = create_agent_stack(database, OWNER)
    tid = tenant.id
    sub, person = _bound_space_with_person(database, tid)
    role_id = _role_with_agent(database, tid, agent.id)
    with database() as db:
        orgs.add_members_from_organization(db, OWNER, tid, [person], [role_id])
    with database() as db:
        org_session = create_session(db, PERSON, tid, agent_version_id=version.id, title="org")
        org_id = org_session.id
    with database() as db:
        everything = {row.id for row in list_sessions_for_platform_admin(db, ADMIN)}
    assert {owner_session.id, org_id} <= everything
    with database() as db:
        by_org = {row.id for row in list_sessions_for_platform_admin(db, ADMIN, org_unit_id=sub)}
    assert by_org == {org_id}
    with database() as db:
        by_agent = {row.id for row in list_sessions_for_platform_admin(db, ADMIN, agent_id=agent.id)}
    assert {owner_session.id, org_id} <= by_agent
    with database() as db:
        with pytest.raises(Forbidden):  # a space owner is not a platform administrator
            list_sessions_for_platform_admin(db, OWNER)


def test_platform_admin_lists_all_spaces_others_are_refused(database):
    from nexus_platform.tenants.service import list_all_tenants
    _platform_admin(database)
    tenant, *_ = create_agent_stack(database, OWNER)
    with database() as db:
        assert tenant.id in {row.id for row in list_all_tenants(db, ADMIN)}
    with database() as db:
        with pytest.raises(Forbidden):
            list_all_tenants(db, OWNER)
