"""System space: builtin tools and skills are assignable in every space (openspec 2026-11-07-skill-evolution, S1).

A space that never enabled a tool can still bind and publish it; a space can switch a builtin resource off for itself
only; the system space is never listed. "Effective" means assignable, not enabled: an agent still has to bind it.
"""
import pytest
from sqlalchemy import select

from nexus_core.native import BUILTIN_TOOL_NAMES
from nexus_core.platform import SYSTEM_TENANT_ID, Principal
from nexus_platform.agents.service import create_agent, publish_agent
from nexus_platform.authz.resources import authorize_resource, register_resource
from nexus_platform.errors import Forbidden
from nexus_platform.models.service import create_model_profile
from nexus_platform.persistence.models import (
    AgentDraftBindingRecord, PlatformResourceRecord, ResourceBindingRecord, TenantRecord,
)
from nexus_platform.system import (
    disable_builtin, enable_builtin_resource, ensure_system_resources, list_disabled,
)
from nexus_platform.tenants.service import create_tenant, list_tenants
from test_platform import database  # noqa: F401  (pytest fixture)

ALICE = Principal(id='alice', issuer='test')
BOB = Principal(id='bob', issuer='test')


def _space(factory, principal=ALICE, kind='enterprise', name='Space'):
    """A space with a model profile; no tool is enabled in it. Returns (tenant, model_version)."""
    with factory() as db:
        tenant = create_tenant(db, principal, name)
        _, model_version = create_model_profile(db, principal, tenant.id, name='M', provider='openai',
                                                model_name='test', options={'base_url': 'https://model.example/v1'})
    if kind != 'enterprise':
        with factory() as db, db.begin():
            db.get(TenantRecord, tenant.id).kind = kind
    return tenant, model_version


def _agent(factory, principal, tenant, model_version, tools):
    bindings = [{'kind': 'tool', 'resource_id': t, 'resource_version_id': 'v1',
                 'source_tenant_id': str(tenant.id), 'config': {}} for t in tools]
    with factory() as db:
        return create_agent(db, principal, tenant.id, name='A', description='', runtime_type='native',
                            instructions='', model_profile_version_id=model_version.id, budgets={},
                            bindings=bindings).id


def test_system_space_is_created_once_and_registers_every_builtin_tool(database):
    with database() as db:
        assert ensure_system_resources(db) == len(BUILTIN_TOOL_NAMES)
    with database() as db:
        assert ensure_system_resources(db) == 0
    with database() as db:
        tenant = db.get(TenantRecord, SYSTEM_TENANT_ID)
        assert tenant.kind == 'system'
        names = set(db.scalars(select(PlatformResourceRecord.resource_id).where(
            PlatformResourceRecord.tenant_id == SYSTEM_TENANT_ID, PlatformResourceRecord.kind == 'tool')))
    assert names == set(BUILTIN_TOOL_NAMES)


@pytest.mark.parametrize('kind', ['enterprise'])
def test_any_space_binds_and_publishes_builtin_tools_without_enabling_them(database, kind):
    with database() as db:
        ensure_system_resources(db)
    tenant, model_version = _space(database, kind=kind)
    agent_id = _agent(database, ALICE, tenant, model_version, ['load_skill', 'read_memory'])
    with database() as db:
        drafts = db.scalars(select(AgentDraftBindingRecord).where(AgentDraftBindingRecord.agent_id == agent_id)).all()
        assert {d.source_tenant_id for d in drafts} == {SYSTEM_TENANT_ID}
    with database() as db:
        version = publish_agent(db, ALICE, tenant.id, agent_id)
    with database() as db:
        bound = db.scalars(select(ResourceBindingRecord).where(ResourceBindingRecord.agent_version_id == version.id)).all()
        assert {b.resource_id for b in bound} == {'load_skill', 'read_memory'}
        assert {b.source_tenant_id for b in bound} == {SYSTEM_TENANT_ID}
        # No registration was made in the space itself.
        assert db.scalar(select(PlatformResourceRecord.id).where(
            PlatformResourceRecord.tenant_id == tenant.id, PlatformResourceRecord.kind == 'tool')) is None


def test_a_registration_the_space_made_itself_keeps_its_source(database):
    with database() as db:
        ensure_system_resources(db)
    tenant, model_version = _space(database)
    with database() as db:
        register_resource(db, tenant_id=tenant.id, kind='tool', resource_id='read_memory', version_id='v1')
        db.commit()
    agent_id = _agent(database, ALICE, tenant, model_version, ['read_memory'])
    with database() as db:
        draft = db.scalar(select(AgentDraftBindingRecord).where(AgentDraftBindingRecord.agent_id == agent_id))
        assert draft.source_tenant_id == tenant.id


def test_only_skills_and_tools_are_global(database):
    with database() as db:
        ensure_system_resources(db)
    tenant, _ = _space(database)
    with database() as db, pytest.raises(Forbidden):
        authorize_resource(db, tenant.id, 'knowledge_base', 'whatever', source_tenant_id=SYSTEM_TENANT_ID)
    with database() as db:
        assert authorize_resource(db, tenant.id, 'tool', 'read_memory', source_tenant_id=SYSTEM_TENANT_ID,
                                  resource_version_id='v1').tenant_id == SYSTEM_TENANT_ID
    with database() as db:  # a call that names no source also reaches the builtin registration
        assert authorize_resource(db, tenant.id, 'tool', 'read_memory', resource_version_id='v1').tenant_id == SYSTEM_TENANT_ID


def test_a_space_can_switch_a_builtin_off_for_itself_only(database):
    with database() as db:
        ensure_system_resources(db)
    mine, mine_model = _space(database, ALICE, name='Mine')
    other, other_model = _space(database, BOB, name='Other')
    with database() as db:
        disable_builtin(db, ALICE, mine.id, 'tool', 'read_memory')
    with database() as db:
        assert list_disabled(db, ALICE, mine.id) == [{'kind': 'tool', 'resource_id': 'read_memory'}]
    with database() as db:
        assert list_disabled(db, BOB, other.id) == []
    # The disabled tool is refused at call time and when an agent version is published ...
    with database() as db, pytest.raises(Forbidden, match='disabled'):
        authorize_resource(db, mine.id, 'tool', 'read_memory', source_tenant_id=SYSTEM_TENANT_ID,
                           resource_version_id='v1')
    agent_id = _agent(database, ALICE, mine, mine_model, ['read_memory'])
    with database() as db, pytest.raises(Forbidden):
        publish_agent(db, ALICE, mine.id, agent_id)
    # ... but another space is not affected, and switching it back on restores it.
    other_agent = _agent(database, BOB, other, other_model, ['read_memory'])
    with database() as db:
        publish_agent(db, BOB, other.id, other_agent)
    with database() as db:
        enable_builtin_resource(db, ALICE, mine.id, 'tool', 'read_memory')
    with database() as db:
        publish_agent(db, ALICE, mine.id, agent_id)


def test_the_system_space_is_never_listed(database):
    with database() as db:
        ensure_system_resources(db)
    _space(database)
    with database() as db:
        assert SYSTEM_TENANT_ID not in {tenant.id for tenant, _ in list_tenants(db, ALICE)}
