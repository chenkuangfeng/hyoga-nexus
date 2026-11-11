"""Personal and enterprise ownership of agents and knowledge bases (openspec 2026-11-11-enterprise-saas E0).

- Personal resources are maintained only by their creator; owners and admins may see, archive / delete and
  convert them, but not edit them.
- Enterprise resources are maintained by holders of ``enterprise_agents:manage`` / ``enterprise_kbs:manage``
  (owners and admins by default), whoever created them; enterprise bases may also name content maintainers.
- Role grants give use (view, run) only; agents may not depend on someone else's personal knowledge base.
"""
import pytest
from fastapi.testclient import TestClient

from nexus_api.dependencies.platform import get_database_session, get_principal
from nexus_api.main import app
from nexus_core.platform import Principal, TenantRole
from nexus_platform.agents import access as agent_access
from nexus_platform.agents.service import (archive_agent, convert_agent_to_enterprise, create_agent, publish_agent,
                                           update_agent_draft)
from nexus_platform.errors import Conflict, Forbidden, InvalidConfiguration, NotFound
from nexus_platform.knowledge import ownership, service
from nexus_platform.models.service import create_model_profile
from nexus_platform.persistence.models import AgentRecord, AuditRecord, KnowledgeBaseRecord
from nexus_platform.tenants import roles
from nexus_platform.tenants.service import add_member, create_tenant

from test_platform import database  # noqa: F401 (pytest fixture)
from test_tenant_roles import _uid

OWNER = Principal('own-owner', 'test')
ADMIN = Principal('own-admin', 'test')
MEMBER = Principal('own-member', 'test')
OTHER = Principal('own-other', 'test')
OUTSIDER = Principal('own-outsider', 'test')


@pytest.fixture
def env(database, deployment_config, tmp_path):
    """One enterprise: owner, admin, and two contributors who may write agents (``agents:write``)."""
    deployment_config(f'[knowledge]\ndata_dir = "{tmp_path / "kdata"}"\n')
    with database() as db:
        tenant = create_tenant(db, OWNER, 'Acme')
        tid = tenant.id
    with database() as db:
        add_member(db, OWNER, tid, ADMIN, TenantRole.ADMIN)
    for principal in (MEMBER, OTHER):
        with database() as db:
            add_member(db, OWNER, tid, principal, TenantRole.CONTRIBUTOR)
    with database() as db:
        writer = roles.create_role(db, OWNER, tid, 'writer', ['agents'], ['agents:read', 'agents:write'])
    for principal in (MEMBER, OTHER):
        with database() as db:
            roles.assign_role(db, OWNER, tid, _uid(database, principal), writer.id)
    with database() as db:
        _, model_version = create_model_profile(
            db, OWNER, tid, name='Model', provider='openai', model_name='test-model',
            options={'base_url': 'https://model.example/v1'})
    return database, tid, model_version.id


def _agent(factory, principal, tid, model_id, name, *, ownership='personal', bindings=()):
    with factory() as db:
        return create_agent(db, principal, tid, name=name, description='', runtime_type='native',
                            instructions='Help', model_profile_version_id=model_id, budgets={'max_rounds': 3},
                            bindings=list(bindings), ownership=ownership).id


def _edit(factory, principal, tid, agent_id, model_id, *, bindings=()):
    with factory() as db:
        update_agent_draft(db, principal, tid, agent_id, name='Renamed', description='', runtime_type='native',
                           instructions='Help more', model_profile_version_id=model_id, budgets={'max_rounds': 3},
                           bindings=list(bindings))


def _kb(factory, principal, tid, name, *, ownership='personal'):
    with factory() as db, db.begin():
        user = _uid_in(db, principal)
        return service.create_base(db, tid, user, name=name, indexing={'vector': False, 'keyword': True},
                                   ownership=ownership).id


def _uid_in(db, principal):
    from nexus_platform.identity.service import resolve_user
    return resolve_user(db, principal).id


def _kb_binding(tid, kb_id):
    return {'kind': 'knowledge_base', 'resource_id': str(kb_id), 'source_tenant_id': tid, 'config': {}}


# ---- agents ---------------------------------------------------------------------------------------------------

def test_personal_agent_is_maintained_only_by_its_creator(env):
    factory, tid, model_id = env
    agent_id = _agent(factory, MEMBER, tid, model_id, 'Mine')
    _edit(factory, MEMBER, tid, agent_id, model_id)
    with factory() as db:
        publish_agent(db, MEMBER, tid, agent_id)
    for principal in (OWNER, ADMIN):
        with pytest.raises(Forbidden):
            _edit(factory, principal, tid, agent_id, model_id)
        with factory() as db:
            record = db.get(AgentRecord, agent_id)
            assert agent_access.agent_permissions(db, tid, _uid(factory, principal), record) == {'view', 'manage'}
    with factory() as db:
        assert agent_access.visible_agent_ids(db, tid, _uid(factory, OTHER)) == set()
    # Governance: an admin may archive a member's personal agent without being able to edit it.
    with factory() as db:
        archive_agent(db, ADMIN, tid, agent_id)


def test_enterprise_agent_is_maintained_by_enterprise_managers_not_its_creator(env):
    factory, tid, model_id = env
    with pytest.raises(Forbidden):
        _agent(factory, MEMBER, tid, model_id, 'Not allowed', ownership='enterprise')
    with factory() as db:
        manager = roles.create_role(db, OWNER, tid, 'agent-manager', ['agents'], ['enterprise_agents:manage'])
    member_id = _uid(factory, MEMBER)
    with factory() as db:
        roles.assign_role(db, OWNER, tid, member_id, manager.id)
    agent_id = _agent(factory, MEMBER, tid, model_id, 'Company bot', ownership='enterprise')
    _edit(factory, ADMIN, tid, agent_id, model_id)  # admins hold enterprise_agents:manage by default
    with factory() as db:
        assert agent_access.visible_agent_ids(db, tid, member_id) == {agent_id}
    with factory() as db:
        roles.unassign_role(db, OWNER, tid, member_id, manager.id)
    with pytest.raises(NotFound):  # the creator no longer maintains, nor sees, the enterprise agent
        _edit(factory, MEMBER, tid, agent_id, model_id)


def test_role_grants_assign_use_only(env):
    factory, tid, model_id = env
    agent_id = _agent(factory, OWNER, tid, model_id, 'Assigned', ownership='enterprise')
    with factory() as db:
        version = publish_agent(db, OWNER, tid, agent_id)
    with factory() as db:
        users = roles.create_role(db, OWNER, tid, 'users', ['agents'], ['agents:read'])
    with factory() as db:
        agent_access.set_agent_grants(db, OWNER, tid, users.id, agent_id, ['view', 'run'])
    with factory() as db:
        roles.assign_role(db, OWNER, tid, _uid(factory, OTHER), users.id)
    with factory() as db:
        assert agent_access.can_use_agent(db, tid, _uid(factory, OTHER), db.get(AgentRecord, agent_id))
    with pytest.raises(Forbidden):
        _edit(factory, OTHER, tid, agent_id, model_id)
    with factory() as db:
        with pytest.raises(InvalidConfiguration):
            agent_access.set_agent_grants(db, OWNER, tid, users.id, agent_id, ['manage'])
    # Owners cannot hand out use of a member's personal agent: they do not hold run on it.
    personal = _agent(factory, MEMBER, tid, model_id, 'Private')
    with factory() as db:
        with pytest.raises(Forbidden):
            agent_access.set_agent_grants(db, OWNER, tid, users.id, personal, ['run'])
    assert version.agent_id == agent_id


def test_agents_cannot_depend_on_someone_elses_personal_knowledge_base(env):
    factory, tid, model_id = env
    mine = _kb(factory, MEMBER, tid, 'member notes')
    theirs = _kb(factory, OTHER, tid, 'other notes')
    company = _kb(factory, OWNER, tid, 'handbook', ownership='enterprise')
    _agent(factory, MEMBER, tid, model_id, 'Own notes', bindings=[_kb_binding(tid, mine), _kb_binding(tid, company)])
    with pytest.raises(InvalidConfiguration, match='knowledge_binding_ownership'):
        _agent(factory, MEMBER, tid, model_id, 'Borrowed', bindings=[_kb_binding(tid, theirs)])
    with pytest.raises(InvalidConfiguration, match='knowledge_binding_ownership'):
        _agent(factory, OWNER, tid, model_id, 'Company', ownership='enterprise', bindings=[_kb_binding(tid, mine)])
    _agent(factory, OWNER, tid, model_id, 'Company', ownership='enterprise', bindings=[_kb_binding(tid, company)])


def test_convert_personal_agent_and_its_knowledge_base(env):
    factory, tid, model_id = env
    kb_id = _kb(factory, MEMBER, tid, 'useful notes')
    agent_id = _agent(factory, MEMBER, tid, model_id, 'Useful', bindings=[_kb_binding(tid, kb_id)])
    with factory() as db:
        with pytest.raises(Forbidden):
            convert_agent_to_enterprise(db, MEMBER, tid, agent_id)
    with factory() as db:
        with pytest.raises(Conflict):  # the bound personal base must be converted first
            convert_agent_to_enterprise(db, ADMIN, tid, agent_id)
    with factory() as db, db.begin():
        ownership.convert_to_enterprise(db, tid, _uid_in(db, ADMIN), kb_id)
    with factory() as db:
        assert convert_agent_to_enterprise(db, ADMIN, tid, agent_id).ownership == 'enterprise'
    with pytest.raises(NotFound):  # the creator lost maintenance and has no use grant
        _edit(factory, MEMBER, tid, agent_id, model_id)
    _edit(factory, ADMIN, tid, agent_id, model_id)
    with factory() as db:
        actions = {row.action for row in db.query(AuditRecord).filter(AuditRecord.tenant_id == tid)}
    assert {'agent.converted_to_enterprise', 'knowledge_base.converted_to_enterprise'} <= actions


# ---- knowledge bases ------------------------------------------------------------------------------------------

def test_personal_knowledge_base_is_managed_by_its_creator_and_governed_by_admins(env):
    factory, tid, _ = env
    kb_id = _kb(factory, MEMBER, tid, 'diary')
    member, admin = _uid(factory, MEMBER), _uid(factory, ADMIN)
    with factory() as db, db.begin():
        service.update_base(db, tid, member, kb_id, {'description': 'mine'})
    with factory() as db:
        with pytest.raises(Forbidden):
            service.update_base(db, tid, admin, kb_id, {'description': 'theirs'})
        with pytest.raises(Forbidden):
            service.prepare_upload(db, tid, admin, kb_id, 'a.txt', b'x', 100)
    with factory() as db, db.begin():
        view = service.base_view(db, db.get(KnowledgeBaseRecord, kb_id), tid, admin)
        assert (view['ownership'], view['can_manage'], view['can_maintain'], view['can_govern']) == (
            'personal', False, False, True)
        with pytest.raises(InvalidConfiguration):  # personal bases have no maintainers
            ownership.add_maintainer(db, tid, member, kb_id, admin)
    with factory() as db, db.begin():
        service.delete_base(db, tid, admin, kb_id)


def test_enterprise_knowledge_base_maintainers_maintain_content_only(env):
    factory, tid, _ = env
    with pytest.raises(Forbidden):
        _kb(factory, MEMBER, tid, 'not allowed', ownership='enterprise')
    kb_id = _kb(factory, OWNER, tid, 'policies', ownership='enterprise')
    owner, admin, member = _uid(factory, OWNER), _uid(factory, ADMIN), _uid(factory, MEMBER)
    with factory() as db, db.begin():  # admins manage enterprise bases they did not create
        service.update_base(db, tid, admin, kb_id, {'description': 'company policies'})
    with factory() as db:
        with pytest.raises(Forbidden):
            service.prepare_upload(db, tid, member, kb_id, 'a.txt', b'x', 100)
    with factory() as db, db.begin():
        rows = ownership.add_maintainer(db, tid, owner, kb_id, member)
        assert [row['user_id'] for row in rows] == [str(member)]
        with pytest.raises(NotFound):
            ownership.add_maintainer(db, tid, owner, kb_id, _uid_in(db, OUTSIDER))
    with factory() as db:
        service.prepare_upload(db, tid, member, kb_id, 'a.txt', b'x', 100)
        with pytest.raises(Forbidden):
            service.update_base(db, tid, member, kb_id, {'description': 'nope'})
        with pytest.raises(Forbidden):
            service.delete_base(db, tid, member, kb_id)
        with pytest.raises(Forbidden):
            ownership.list_maintainers(db, tid, member, kb_id)
    with factory() as db, db.begin():
        view = service.base_view(db, db.get(KnowledgeBaseRecord, kb_id), tid, member)
        assert (view['can_maintain'], view['can_manage'], view['can_edit']) == (True, False, True)
        ownership.remove_maintainer(db, tid, owner, kb_id, member)
    with factory() as db:
        with pytest.raises(Forbidden):
            service.prepare_upload(db, tid, member, kb_id, 'a.txt', b'x', 100)


# ---- admin API ------------------------------------------------------------------------------------------------

def test_admin_api_creates_enterprise_resources_and_manages_maintainers(env):
    factory, tid, model_id = env
    app.state.session_factory = factory

    def override_db():
        with factory() as db:
            yield db

    current = {'principal': OWNER}
    app.dependency_overrides[get_database_session] = override_db
    app.dependency_overrides[get_principal] = lambda: current['principal']
    try:
        with TestClient(app) as client:
            base = f'/api/v1/tenants/{tid}'
            agent = client.post(f'{base}/admin/agents', json={
                'name': 'Company bot', 'runtime_type': 'native', 'instructions': 'Help',
                'model_profile_version_id': str(model_id)})
            assert agent.status_code == 201, agent.text
            assert (agent.json()['ownership'], agent.json()['can_maintain']) == ('enterprise', True)
            kb = client.post(f'{base}/admin/knowledge/bases', json={
                'name': 'Handbook', 'indexing_strategy': {'vector': False, 'keyword': True}})
            assert kb.status_code == 201, kb.text
            kb_id = kb.json()['id']
            assert kb.json()['ownership'] == 'enterprise'
            member = str(_uid(factory, MEMBER))
            added = client.post(f'{base}/admin/knowledge/bases/{kb_id}/maintainers', json={'user_id': member})
            assert added.status_code == 201, added.text
            listed = client.get(f'{base}/admin/knowledge/bases/{kb_id}/maintainers').json()['items']
            assert [row['user_id'] for row in listed] == [member]
            assert client.delete(f'{base}/admin/knowledge/bases/{kb_id}/maintainers/{member}').status_code == 204
            current['principal'] = MEMBER
            personal = client.post(f'{base}/agents', json={
                'name': 'Mine', 'runtime_type': 'native', 'instructions': 'Help',
                'model_profile_version_id': str(model_id)})
            assert personal.status_code == 201, personal.text
            assert (personal.json()['ownership'], personal.json()['owned_by_me']) == ('personal', True)
            listed = client.get(f'{base}/agents').json()
            assert [(row['name'], row['status'], row['can_maintain']) for row in listed] == [('Mine', 'draft', True)]
            denied = client.post(f'{base}/admin/agents', json={
                'name': 'Sneaky', 'runtime_type': 'native', 'instructions': 'Help',
                'model_profile_version_id': str(model_id)})
            assert denied.status_code == 403
            current['principal'] = ADMIN
            converted = client.post(f'{base}/admin/agents/{personal.json()["id"]}/convert-to-enterprise')
            assert converted.status_code == 200, converted.text
            assert converted.json()['ownership'] == 'enterprise'
    finally:
        app.dependency_overrides.clear()
        app.state.session_factory = None
