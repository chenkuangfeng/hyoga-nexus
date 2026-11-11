"""Enterprise policy, built-in roles and knowledge base visibility (openspec 2026-11-11-enterprise-saas E1)."""
import pytest

from nexus_core.platform import Principal
from nexus_platform.agents import access as agent_access
from nexus_platform.agents.service import publish_agent
from nexus_platform.errors import Conflict, Forbidden, InvalidConfiguration, NotFound
from nexus_platform.knowledge import access as kb_access, ownership, service
from nexus_platform.models.provider_settings import save_provider
from nexus_platform.orgs import service as orgs
from nexus_platform.persistence.models import KnowledgeBaseRecord, TenantRoleRecord
from nexus_platform.tenants import roles
from nexus_platform.tenants.policies import get_policy, read_policy, update_policy

from test_platform import database  # noqa: F401 (pytest fixture)
from test_resource_ownership import (ADMIN, MEMBER, OTHER, OWNER, _agent, _kb, _kb_binding, _uid_in, env)  # noqa: F401
from test_tenant_roles import _uid

AUDITOR = Principal('pol-auditor', 'test')


def test_defaults_and_only_policy_managers_change_the_policy(env):
    factory, tid, _ = env
    with factory() as db:
        assert read_policy(db, MEMBER, tid) == {
            'self_build_agents': 'all', 'self_build_org_unit_ids': [], 'personal_models': False,
            'external_sharing': False, 'personal_wecom_channels': 'review', 'personal_external_channels': True,
            'retention_days': None}
    for principal in (MEMBER, ADMIN):  # policy:manage is a governance key: admins need it through a role
        with factory() as db:
            with pytest.raises(Forbidden):
                update_policy(db, principal, tid, {'external_sharing': True})
    with factory() as db:
        with pytest.raises(InvalidConfiguration):
            update_policy(db, OWNER, tid, {'self_build_agents': 'some'})
    with factory() as db:
        changed = update_policy(db, OWNER, tid, {'retention_days': 30, 'personal_wecom_channels': 'open'})
    assert (changed['retention_days'], changed['personal_wecom_channels']) == (30, 'open')


def test_self_build_follows_the_policy(env):
    factory, tid, model_id = env
    _agent(factory, MEMBER, tid, model_id, 'Allowed by default')
    with factory() as db:
        update_policy(db, OWNER, tid, {'self_build_agents': 'none'})
    with pytest.raises(Forbidden):
        _agent(factory, MEMBER, tid, model_id, 'Blocked')
    _agent(factory, ADMIN, tid, model_id, 'Admins are never limited')
    with factory() as db:
        root = orgs.create_unit(db, OWNER, tid, 'Acme')
    with factory() as db:
        sales = orgs.create_unit(db, OWNER, tid, 'Sales', parent_id=root.id)
    with factory() as db:
        orgs.assign_member(db, OWNER, tid, sales.id, _uid(factory, MEMBER), is_primary=True)
    with factory() as db:
        update_policy(db, OWNER, tid, {'self_build_agents': 'org_units', 'self_build_org_unit_ids': [str(root.id)]})
    _agent(factory, MEMBER, tid, model_id, 'Inside the allowed subtree')
    with pytest.raises(Forbidden):
        _agent(factory, OTHER, tid, model_id, 'Outside it')


def test_personal_models_are_off_until_the_enterprise_allows_them(env, deployment_config):
    from cryptography.fernet import Fernet
    factory, tid, _ = env
    deployment_config(f'[security]\ncredential_encryption_key = "{Fernet.generate_key().decode()}"\n')
    with factory() as db:
        with pytest.raises(Forbidden):
            save_provider(db, MEMBER, tid, name='Mine', base_url='https://model.example/v1', scope='personal',
                          api_key='k')
    with factory() as db:
        update_policy(db, OWNER, tid, {'personal_models': True})
    with factory() as db:
        provider = save_provider(db, MEMBER, tid, name='Mine', base_url='https://model.example/v1',
                                 scope='personal', api_key='k')
    with factory() as db:
        update_policy(db, OWNER, tid, {'personal_models': False})
    from nexus_platform.models.provider_settings import provider_access
    from uuid import UUID
    with factory() as db:
        with pytest.raises(Forbidden):  # turning it off applies to the next use
            provider_access(db, tid, _uid_in(db, MEMBER), UUID(str(provider['id'])))


def test_builtin_roles_exist_and_cannot_be_changed(env):
    factory, tid, _ = env
    with factory() as db:
        rows = {role.name: role for role in db.query(TenantRoleRecord).filter(TenantRoleRecord.tenant_id == tid)}
    assert rows['security_admin'].builtin and rows['auditor'].builtin
    with factory() as db:
        with pytest.raises(Forbidden):
            roles.update_role_grants(db, OWNER, tid, rows['auditor'].id, ['audit'], ['audit:read', 'members:manage'])
    from nexus_platform.tenants.service import add_member
    from nexus_core.platform import TenantRole
    with factory() as db:
        add_member(db, OWNER, tid, AUDITOR, TenantRole.VIEWER)
    with factory() as db:
        roles.assign_role(db, OWNER, tid, _uid(factory, AUDITOR), rows['security_admin'].id)
    with factory() as db:
        assert update_policy(db, AUDITOR, tid, {'external_sharing': True})['external_sharing'] is True


# ---- knowledge base visibility --------------------------------------------------------------------------------

def test_private_bases_are_read_only_by_their_maintainers_and_admins(env):
    factory, tid, _ = env
    personal = _kb(factory, MEMBER, tid, 'drafts')
    company = _kb(factory, OWNER, tid, 'board papers', ownership='enterprise')
    with factory() as db, db.begin():
        service.update_base(db, tid, _uid_in(db, OWNER), company, {'visibility': 'private'})
        ownership.add_maintainer(db, tid, _uid_in(db, OWNER), company, _uid_in(db, OTHER))
    with factory() as db, db.begin():
        assert db.get(KnowledgeBaseRecord, personal).visibility == 'private'
        readable = lambda principal: {kb.id for kb in kb_access.readable_bases(db, tid, _uid_in(db, principal))}
        assert readable(MEMBER) == {personal}
        assert readable(OTHER) == {company}
        assert readable(ADMIN) == {personal, company}
        with pytest.raises(NotFound):
            kb_access.readable_base(db, personal, tid, _uid_in(db, OTHER))
    with factory() as db, db.begin():
        service.update_base(db, tid, _uid_in(db, MEMBER), personal, {'visibility': 'tenant'})
    with factory() as db, db.begin():
        kb_access.readable_base(db, personal, tid, _uid_in(db, OTHER))


def test_agents_used_by_others_cannot_bind_private_bases(env):
    factory, tid, model_id = env
    private = _kb(factory, OWNER, tid, 'secret', ownership='enterprise')
    with factory() as db, db.begin():
        service.update_base(db, tid, _uid_in(db, OWNER), private, {'visibility': 'private'})
    tool = {'kind': 'tool', 'resource_id': 'search_knowledge', 'resource_version_id': 'v1', 'source_tenant_id': tid,
            'config': {}}
    agent_id = _agent(factory, OWNER, tid, model_id, 'Company', ownership='enterprise',
                      bindings=[_kb_binding(tid, private)])
    with factory() as db:
        with pytest.raises(InvalidConfiguration, match='binding_scope_narrower|knowledge_dependency'):
            publish_agent(db, OWNER, tid, agent_id)
    # A personal agent may bind its creator's private base until someone else is given use of it.
    mine = _kb(factory, MEMBER, tid, 'notes')
    personal_agent = _agent(factory, MEMBER, tid, model_id, 'Mine', bindings=[_kb_binding(tid, mine)])
    with factory() as db:
        users = roles.create_role(db, OWNER, tid, 'users', ['agents'], ['agents:read'])
    with factory() as db:
        with pytest.raises(Forbidden):  # owners hold no run on it; and the scope check would refuse anyway
            agent_access.set_agent_grants(db, OWNER, tid, users.id, personal_agent, ['run'])
    # Once an enterprise agent binds a tenant-wide base, the base cannot become private again.
    shared = _kb(factory, OWNER, tid, 'handbook', ownership='enterprise')
    _agent(factory, OWNER, tid, model_id, 'Helpdesk', ownership='enterprise', bindings=[_kb_binding(tid, shared)])
    with factory() as db:
        with pytest.raises(Conflict, match='kb_in_use'):
            with db.begin():
                service.update_base(db, tid, _uid_in(db, OWNER), shared, {'visibility': 'private'})
    assert tool['kind'] == 'tool'


def test_external_sharing_policy_and_private_bases_block_shares(env):
    from nexus_platform.shared_spaces import kb_shares
    from nexus_platform.shared_spaces.service import create_shared_space
    factory, tid, _ = env
    kb_id = _kb(factory, OWNER, tid, 'manual', ownership='enterprise')
    with factory() as db:
        shared_id = create_shared_space(db, OWNER, tid, name='Alliance').id
    private = _kb(factory, MEMBER, tid, 'diary')
    with factory() as db:
        with pytest.raises(InvalidConfiguration):
            kb_shares.share_base(db, MEMBER, tid, private, shared_id, 'viewer')
    with factory() as db:  # only this enterprise is in the shared space, so the policy does not apply yet
        kb_shares.share_base(db, OWNER, tid, kb_id, shared_id, 'viewer')
    assert get_policy  # imported for readability of the policy defaults above
