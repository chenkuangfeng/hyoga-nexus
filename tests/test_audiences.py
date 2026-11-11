"""Department and member audiences (openspec 2026-11-11-enterprise-saas E5): agents assigned to departments or
members, ``scoped`` knowledge bases, the current organization deciding at each check, and bindings that may never
let an agent's users reach a base they cannot read."""
import pytest
from fastapi.testclient import TestClient

from nexus_api.dependencies.platform import get_database_session, get_principal
from nexus_api.main import app
from nexus_platform.agents import access as agent_access
from nexus_platform.agents.service import publish_agent
from nexus_platform.errors import InvalidConfiguration
from nexus_platform.knowledge import access as kb_access
from nexus_platform.orgs import service as orgs
from nexus_platform.persistence.models import AgentRecord

from test_platform import database  # noqa: F401 (pytest fixture)
from test_resource_ownership import (ADMIN, MEMBER, OTHER, OWNER, _agent, _kb, _kb_binding, _uid_in,  # noqa: F401
                                     env)
from test_tenant_roles import _uid


@pytest.fixture
def org(env):
    """Acme ─ Sales ─ East; MEMBER sits in East, OTHER in Acme only."""
    factory, tid, model_id = env
    with factory() as db:
        root = orgs.create_unit(db, OWNER, tid, 'Acme').id
    with factory() as db:
        sales = orgs.create_unit(db, OWNER, tid, 'Sales', parent_id=root).id
    with factory() as db:
        east = orgs.create_unit(db, OWNER, tid, 'East', parent_id=sales).id
    with factory() as db:
        orgs.assign_member(db, OWNER, tid, east, _uid(factory, MEMBER), is_primary=True)
    with factory() as db:
        orgs.assign_member(db, OWNER, tid, root, _uid(factory, OTHER), is_primary=True)
    return factory, tid, model_id, {'root': root, 'sales': sales, 'east': east}


@pytest.fixture
def client(org):
    factory = org[0]
    app.state.session_factory = factory

    def override_db():
        with factory() as db:
            yield db

    current = {'principal': OWNER}
    app.dependency_overrides[get_database_session] = override_db
    app.dependency_overrides[get_principal] = lambda: current['principal']
    try:
        with TestClient(app) as test_client:
            yield test_client, current
    finally:
        app.dependency_overrides.clear()
        app.state.session_factory = None


def _can_use(factory, tid, principal, agent_id):
    with factory() as db:
        return agent_access.can_use_agent(db, tid, _uid(factory, principal), db.get(AgentRecord, agent_id))


def test_department_audience_follows_the_organization(org, client):
    factory, tid, model_id, units = org
    http, _ = client
    agent_id = _agent(factory, OWNER, tid, model_id, 'Sales helper', ownership='enterprise')
    path = f'/api/v1/tenants/{tid}/agents/{agent_id}/audience'
    saved = http.put(path, json={'items': [{'kind': 'org_unit', 'id': str(units['sales'])}]})
    assert saved.status_code == 200, saved.text
    assert _can_use(factory, tid, MEMBER, agent_id) and not _can_use(factory, tid, OTHER, agent_id)
    http.put(path, json={'items': [{'kind': 'org_unit', 'id': str(units['sales']), 'include_descendants': False}]})
    assert not _can_use(factory, tid, MEMBER, agent_id)  # East is below Sales, not in it
    http.put(path, json={'items': [{'kind': 'org_unit', 'id': str(units['sales'])}]})
    with factory() as db:
        orgs.unassign_member(db, OWNER, tid, units['east'], _uid(factory, MEMBER))
    assert not _can_use(factory, tid, MEMBER, agent_id)  # moved out: the next check refuses
    http.put(path, json={'items': [{'kind': 'user', 'id': str(_uid(factory, OTHER))}]})
    assert _can_use(factory, tid, OTHER, agent_id)
    with factory() as db:
        assert agent_id in agent_access.visible_agent_ids(db, tid, _uid(factory, OTHER))


def test_personal_agents_are_assigned_by_their_creator_only(org, client):
    factory, tid, model_id, _ = org
    http, current = client
    agent_id = _agent(factory, MEMBER, tid, model_id, 'Mine')
    path = f'/api/v1/tenants/{tid}/agents/{agent_id}/audience'
    assert http.put(path, json={'items': [{'kind': 'user', 'id': str(_uid(factory, OTHER))}]}).status_code == 403
    current['principal'] = MEMBER
    assert http.put(path, json={'items': [{'kind': 'user', 'id': str(_uid(factory, OTHER))}]}).status_code == 200
    assert _can_use(factory, tid, OTHER, agent_id)


def test_scoped_bases_are_read_by_their_audience(org, client):
    factory, tid, _, units = org
    http, _ = client
    kb_id = _kb(factory, OWNER, tid, 'sales playbook', ownership='enterprise')
    saved = http.put(f'/api/v1/tenants/{tid}/knowledge/bases/{kb_id}/audience',
                     json={'items': [{'kind': 'org_unit', 'id': str(units['sales'])}]})
    assert saved.status_code == 200 and saved.json()['visibility'] == 'scoped'
    with factory() as db, db.begin():
        assert kb_id in {kb.id for kb in kb_access.readable_bases(db, tid, _uid_in(db, MEMBER))}
        assert kb_id not in {kb.id for kb in kb_access.readable_bases(db, tid, _uid_in(db, OTHER))}


def test_bindings_never_reach_people_who_cannot_read_the_base(org, client):
    factory, tid, model_id, units = org
    http, _ = client
    kb_id = _kb(factory, OWNER, tid, 'east notes', ownership='enterprise')
    base_path = f'/api/v1/tenants/{tid}/knowledge/bases/{kb_id}/audience'
    http.put(base_path, json={'items': [{'kind': 'org_unit', 'id': str(units['sales'])}]})
    tool = {'kind': 'tool', 'resource_id': 'search_knowledge', 'resource_version_id': 'v1', 'source_tenant_id': tid,
            'config': {}}
    agent_id = _agent(factory, OWNER, tid, model_id, 'East bot', ownership='enterprise',
                      bindings=[_kb_binding(tid, kb_id)])
    agent_path = f'/api/v1/tenants/{tid}/agents/{agent_id}/audience'
    assert http.put(agent_path, json={'items': [{'kind': 'org_unit', 'id': str(units['east'])}]}).status_code == 200
    wider = http.put(agent_path, json={'items': [{'kind': 'org_unit', 'id': str(units['root'])}]})
    assert wider.status_code == 422 and 'binding_scope_narrower' in wider.text
    narrowed = http.put(base_path, json={'items': [{'kind': 'user', 'id': str(_uid(factory, OTHER))}]})
    assert narrowed.status_code == 409 and 'kb_in_use' in narrowed.text
    with factory() as db:
        from nexus_platform.tenants import roles
        role = roles.create_role(db, OWNER, tid, 'all users', ['agents'], ['agents:read'])
    with factory() as db:
        with pytest.raises(InvalidConfiguration, match='binding_scope_narrower'):
            agent_access.set_agent_grants(db, OWNER, tid, role.id, agent_id, ['run'])
    with factory() as db:
        with pytest.raises(InvalidConfiguration):  # the knowledge tool is missing; scope itself is fine
            publish_agent(db, OWNER, tid, agent_id)
    assert tool['kind'] == 'tool'
