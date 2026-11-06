"""Long-term memory switches: space, member and agent levels (openspec 2026-11-05-memory-switches)."""
import asyncio
import itertools
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from nexus_core.platform import utc_now
from nexus_core.runtime import RuntimeFault
from nexus_memory import switches as rules
from nexus_platform.memory import capture
from nexus_platform.memory import switches
from nexus_platform.memory.repository import SqlMemoryRepository
from nexus_platform.persistence.models import (
    AuditRecord,
    MemoryCaptureJobRecord,
    RunRecord,
    SessionMemorySnapshotRecord,
)
from nexus_platform.runs.preparation import prepare_execution
from nexus_platform.runs.service import claim_next
from nexus_platform.runs.store import DurableRuntimeStore

from test_memory_capture import _enable, _enqueue, _job, _messages, _scripted
from test_model_settings import settings_client  # noqa: F401 (pytest fixture)
from test_native_runtime import stack
from test_platform import database  # noqa: F401 (pytest fixture)

MEMORY_TOOLS = sorted(rules.MEMORY_TOOL_NAMES)


# ---------------------------------------------------------------- pure rules

@pytest.mark.parametrize('space,user,agent', list(itertools.product([True, False], [True, False], [None, True, False])))
def test_memory_is_available_only_when_every_level_allows_it(space, user, agent):
    state = rules.resolve(space_enabled=space, write_mode='auto', user_enabled=user, agent_enabled=agent)
    assert state.available is (space and user and agent is not False)
    expected = None if state.available else (
        'space_disabled' if not space else 'agent_disabled' if agent is False else 'user_disabled')
    assert state.reason == expected


def test_explicit_mode_keeps_memory_but_disallows_capture():
    explicit = rules.resolve(space_enabled=True, write_mode='explicit', user_enabled=True)
    assert explicit.available and not explicit.capture_allowed
    assert rules.resolve(space_enabled=True, write_mode='auto', user_enabled=True).capture_allowed
    # An unknown stored mode falls back to the default instead of failing a Run.
    assert rules.resolve(space_enabled=True, write_mode='bogus', user_enabled=True).write_mode == 'auto'


def test_agent_preference_only_turns_memory_off_with_an_explicit_false():
    assert rules.agent_preference({'memory': {'enabled': False}}) is False
    assert rules.agent_preference({'memory': {'enabled': True}}) is None
    assert rules.agent_preference({'memory': {'enabled': 'no'}}) is None
    assert rules.agent_preference(None) is None and rules.agent_preference({}) is None


@pytest.mark.parametrize('group', [[], {'enabled': 1}, {'enabled': True, 'extra': 1}, 'off'])
def test_agent_memory_budget_rejects_anything_but_a_boolean(group):
    with pytest.raises(ValueError):
        rules.validate_agent_budget({'memory': group})


def test_agent_memory_budget_accepts_missing_or_boolean():
    rules.validate_agent_budget({})
    rules.validate_agent_budget({'memory': {}})
    rules.validate_agent_budget({'memory': {'enabled': False}})


# ---------------------------------------------------------------- HTTP contract

def test_space_settings_default_on_and_only_admins_change_them(settings_client, database):  # noqa: F811
    client, path, identity, owner, member, tenant_id = settings_client
    root = path.removesuffix('/model-settings') + '/native'
    assert client.get(root + '/memory-settings').json() == {
        'enabled': True, 'write_mode': 'auto', 'extract_instructions': '', 'embedding_model_version_id': None, 'can_edit': True, 'updated_at': None}

    identity[0] = member
    assert client.get(root + '/memory-settings').json()['can_edit'] is False
    assert client.put(root + '/memory-settings', json={'enabled': False}).status_code == 403

    identity[0] = owner
    assert client.put(root + '/memory-settings', json={'enabled': True, 'write_mode': 'sometimes'}).status_code == 422
    changed = client.put(root + '/memory-settings', json={'enabled': False, 'write_mode': 'explicit'})
    assert changed.status_code == 200, changed.text
    assert changed.json()['enabled'] is False and changed.json()['write_mode'] == 'explicit'

    # Members see the space switch as the reason their memory is off.
    identity[0] = member
    assert client.get(root + '/memory-preferences').json() == {
        'memory_enabled': True, 'effective': False, 'reason': 'space_disabled', 'write_mode': 'explicit'}
    with database() as db:
        actions = [row.action for row in db.query(AuditRecord).filter(AuditRecord.tenant_id == tenant_id)]
    assert 'memory.space_settings' in actions


def test_member_preference_is_their_own_and_keeps_capture_settings(settings_client, database):  # noqa: F811
    client, path, identity, owner, member, tenant_id = settings_client
    root = path.removesuffix('/model-settings') + '/native'
    identity[0] = member
    assert client.get(root + '/memory-preferences').json()['effective'] is True
    off = client.put(root + '/memory-preferences', json={'memory_enabled': False})
    assert off.status_code == 200, off.text
    assert off.json() == {'memory_enabled': False, 'effective': False, 'reason': 'user_disabled', 'write_mode': 'auto'}
    # Capture settings stay at their defaults; the member switch is a separate column.
    assert client.get(root + '/memory-capture').json()['enabled'] is False
    identity[0] = owner
    assert client.get(root + '/memory-preferences').json()['memory_enabled'] is True
    assert client.put(root + '/memory-preferences', json={'memory_enabled': 'maybe'}).status_code == 422


def test_non_members_get_not_found(settings_client):  # noqa: F811
    client, path, identity, owner, member, tenant_id = settings_client
    from nexus_core.platform import Principal
    root = path.removesuffix('/model-settings') + '/native'
    identity[0] = Principal('stranger', 'test')
    assert client.get(root + '/memory-settings').status_code == 404
    assert client.put(root + '/memory-preferences', json={'memory_enabled': False}).status_code == 404


# ---------------------------------------------------------------- Run behavior

def _publish(factory, run, title='Deploy Rule', text='deploy with the checklist'):
    with factory() as db:
        with db.begin():
            repo = SqlMemoryRepository(db)
            draft = repo.create_draft(tenant_id=run.tenant_id, source_run_id=run.id, kind='memory', diff=text,
                                      fingerprint=uuid4().hex + uuid4().hex, base_version=None, origin='foreground',
                                      source_message_ids=())
            entry = repo.create_entry(tenant_id=run.tenant_id, owner_id=run.principal_id, kind='memory',
                                      title=title, project='')
            repo.append_version(entry_id=entry.id, version=1, content=text, source_run_id=run.id,
                                source_draft_id=draft, reviewer_id=run.principal_id,
                                fingerprint=uuid4().hex + uuid4().hex, source_message_ids=())


def _space(factory, principal, tenant_id, enabled, write_mode='auto'):
    with factory() as db:
        switches.set_space_settings(db, principal, tenant_id, enabled=enabled, write_mode=write_mode)


def _member(factory, principal, tenant_id, enabled):
    with factory() as db:
        switches.set_preferences(db, principal, tenant_id, memory_enabled=enabled)


def _prepare(factory):
    with factory() as db:
        task = claim_next(db, 'memory-worker')
    return prepare_execution(factory, task, 'memory-worker'), task


def test_memory_on_injects_the_index_and_offers_memory_tools(database):  # noqa: F811
    _, _, session, run, _ = stack(database, MEMORY_TOOLS)
    _publish(database, run)
    context, _ = _prepare(database)
    assert 'Deploy Rule' in context.messages[0].content
    assert sorted(name for name, _, _ in context.bindings) == MEMORY_TOOLS


@pytest.mark.parametrize('level', ['space', 'member', 'agent'])
def test_any_level_off_removes_index_tools_and_snapshot(database, level):  # noqa: F811
    budgets = {'max_tokens': 100000, 'memory': {'enabled': False}} if level == 'agent' else None
    principal, tenant, session, run, _ = stack(database, MEMORY_TOOLS + ['ask_user'], budgets=budgets)
    _publish(database, run)
    if level == 'space':
        _space(database, principal, tenant.id, False)
    elif level == 'member':
        _member(database, principal, tenant.id, False)
    context, _ = _prepare(database)
    assert context is not None
    assert 'Deploy Rule' not in context.messages[0].content
    assert [name for name, _, _ in context.bindings] == ['ask_user']
    with database() as db:
        assert db.get(SessionMemorySnapshotRecord, session.id) is None


def test_switch_turned_off_mid_run_is_refused_at_authorization(database):  # noqa: F811
    principal, tenant, session, run, _ = stack(database, MEMORY_TOOLS)
    context, task = _prepare(database)
    store = DurableRuntimeStore(database, context, 'memory-worker', task)
    assert asyncio.run(store.authorize('search_memory', 'v1'))
    _member(database, principal, tenant.id, False)
    with pytest.raises(RuntimeFault) as refused:
        asyncio.run(store.authorize('propose_memory_draft', 'v1'))
    assert refused.value.code == 'memory_disabled'
    with database() as db:
        rejected = db.query(AuditRecord).filter(AuditRecord.action == 'memory.call_rejected').one()
    assert rejected.metadata_json == {'tool_name': 'propose_memory_draft', 'reason': 'user_disabled'}


def test_gateway_reports_memory_disabled_to_the_model():
    from nexus_core.runtime import ToolCall
    from nexus_tools.gateway import AuthorizedToolGateway
    from test_native_runtime import registry

    class Access:
        denied_names = []

        async def authorize(self, name, version):
            raise RuntimeFault('memory_disabled')

        async def denied(self, name):
            self.denied_names.append(name)

        async def start(self, call, binding_id):
            return 'inv-1'

        async def finish(self, *args):
            return None

    class Token:
        def check(self):
            return None

    async def echo(args, context):
        raise AssertionError('must not run')

    gateway = AuthorizedToolGateway(registry(echo), Access(), {'echo': 'v1'}, run_id='r', session_id='s', tenant_id='t')
    result = asyncio.run(gateway.execute(ToolCall('c1', 'echo', '{"text": "x"}'), Token()))
    assert result.error_code == 'memory_disabled'


# ---------------------------------------------------------------- capture

def test_capture_is_not_queued_when_memory_is_off_or_explicit(database):  # noqa: F811
    principal, tenant, session, run, _ = stack(database)
    _messages(database, session.id, 4)
    _enable(database, principal, tenant.id)
    _space(database, principal, tenant.id, True, 'explicit')
    assert _enqueue(database, run.id, utc_now()) is None
    _space(database, principal, tenant.id, True, 'auto')
    _member(database, principal, tenant.id, False)
    assert _enqueue(database, run.id, utc_now()) is None
    with database() as db:
        assert db.query(MemoryCaptureJobRecord).count() == 0
    _member(database, principal, tenant.id, True)
    assert _enqueue(database, run.id, utc_now()) is not None


def test_queued_job_completes_without_a_model_call_after_memory_is_turned_off(database):  # noqa: F811
    principal, tenant, session, run, _ = stack(database)
    _messages(database, session.id, 4)
    _enable(database, principal, tenant.id)
    job_id = UUID(_enqueue(database, run.id, utc_now()))
    _space(database, principal, tenant.id, False)
    extractor = _scripted([[{'op': 'add', 'kind': 'memory', 'diff': 'never stored'}]])
    assert capture.run_due(database, extractor, worker_id='w1', now=utc_now() + timedelta(hours=1)) == 'completed'
    assert extractor.calls == []
    assert _job(database, job_id)['error'] == 'memory_disabled'


def test_agent_draft_rejects_invalid_memory_budget(database):  # noqa: F811
    from nexus_platform.agents.service import update_agent_draft
    principal, tenant, session, run, _ = stack(database)
    snapshot = run.config_snapshot
    with database() as db, pytest.raises(ValueError):
        update_agent_draft(db, principal, tenant.id, UUID(snapshot['agent_id']), name='Native', description='',
                           runtime_type='native', instructions='x',
                           model_profile_version_id=UUID(snapshot['model_profile_version_id']),
                           budgets={'memory': {'enabled': 'no'}}, bindings=[])


# ---------------------------------------------------------------- migration

def test_migration_adds_switches_with_memory_on_and_downgrades_cleanly(tmp_path):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, inspect, text
    url = 'sqlite:///' + str(tmp_path / 'memory-switches.db')
    config = Config('alembic.ini')
    config.attributes['database_url'] = url
    command.upgrade(config, 'e5a1c9d3b7f2')
    engine = create_engine(url)
    with engine.begin() as db:
        # A capture settings row written before the switches existed.
        db.execute(text("INSERT INTO memory_capture_settings (tenant_id, owner_user_id, enabled, capacity_policy,"
                        " updated_at) VALUES (:t, :u, 0, 'reject', CURRENT_TIMESTAMP)"), {'t': 'a' * 32, 'u': 'b' * 32})
    command.upgrade(config, 'a3c8e5f1d2b7')
    with engine.connect() as db:
        assert db.execute(text('SELECT memory_enabled FROM memory_capture_settings')).scalar() in (1, True)
    assert 'memory_space_settings' in inspect(engine).get_table_names()
    command.downgrade(config, 'e5a1c9d3b7f2')
    inspector = inspect(create_engine(url))
    assert 'memory_space_settings' not in inspector.get_table_names()
    assert 'memory_enabled' not in {c['name'] for c in inspector.get_columns('memory_capture_settings')}
    command.upgrade(config, 'head')
