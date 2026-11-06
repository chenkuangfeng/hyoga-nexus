"""Session grants for tool approvals (openspec 2026-11-06-tool-call-hardening, section 5)."""
from uuid import UUID

from sqlalchemy import select

from nexus_core.runtime import ModelChunk, ToolCall, ToolDefinition, ToolResult
from nexus_platform.persistence.models import AuditRecord, RunRecord
from nexus_tools.registry import RegisteredTool, ToolRegistry
from nexus_worker.__main__ import run_once

from test_model_settings import settings_client  # noqa: F401 (pytest fixture)
from test_native_runtime import FakeModel, call, run_row, stack
from test_platform import database  # noqa: F401 (pytest fixture)


def _registry(invoked, risk='write'):
    async def write(arguments, context):
        invoked.append(arguments['text'])
        return ToolResult('written')

    def factory(store):
        tools = ToolRegistry()
        tools.register(RegisteredTool(ToolDefinition('write', 'W', {'type': 'object', 'properties': {'text': {'type': 'string'}},
                                                                  'required': ['text']},
                                                     side_effects=True, requires_approval=True, risk=risk), write, lambda r: r.data))
        return tools
    return factory


def _turns(text):
    return FakeModel([[call('write', f'{{"text": "{text}"}}')], [ModelChunk('text', text='done')]])


def _latest_run(database, session_id):
    with database() as db:
        return db.scalar(select(RunRecord).where(RunRecord.session_id == session_id).order_by(RunRecord.created_at.desc()))


def test_session_grant_skips_later_approvals_until_revoked(settings_client, database):  # noqa: F811
    client, _, identity, _, member, _ = settings_client
    principal, tenant, session, run, _ = stack(database, ['write'])
    identity[0] = principal
    invoked = []
    root = f'/api/v1/tenants/{tenant.id}'
    run_once(database, 'worker', model_factory=lambda _: _turns('first'), registry_factory=_registry(invoked))
    assert run_row(database, run.id).status == 'waiting_approval'
    pending = client.get(f'{root}/native/runs/{run.id}/approvals').json()
    assert pending[0]['rememberable'] is True and pending[0]['reason'] == 'policy'
    response = client.post(f'{root}/native/runs/{run.id}/approvals/{pending[0]["id"]}', json={'approve': True, 'remember': 'session'})
    assert response.status_code == 200, response.text
    run_once(database, 'worker', model_factory=lambda _: FakeModel([[ModelChunk('text', text='done')]]),
             registry_factory=_registry(invoked))
    assert invoked == ['first']
    grants = client.get(f'{root}/native/sessions/{session.id}/tool-grants').json()
    assert [g['tool_name'] for g in grants] == ['write'] and grants[0]['risk'] == 'write'

    # A later Run in the same session calls the tool without asking.
    assert client.post(f'{root}/sessions/{session.id}/runs', json={'message': 'again'},
                       headers={'Idempotency-Key': 'grant-2'}).status_code in (200, 201, 202)
    run_once(database, 'worker', model_factory=lambda _: _turns('second'), registry_factory=_registry(invoked))
    second = _latest_run(database, session.id)
    assert second.status == 'completed' and invoked == ['first', 'second']
    with database() as db:
        assert db.scalar(select(AuditRecord).where(AuditRecord.action == 'approval.grant_used')) is not None

    # Other people cannot see or revoke the grant.
    identity[0] = member
    assert client.get(f'{root}/native/sessions/{session.id}/tool-grants').status_code == 404
    assert client.delete(f'{root}/native/sessions/{session.id}/tool-grants/{grants[0]["id"]}').status_code == 404
    identity[0] = principal

    # Revoking takes effect for the next call.
    assert client.delete(f'{root}/native/sessions/{session.id}/tool-grants/{grants[0]["id"]}').status_code == 200
    assert client.get(f'{root}/native/sessions/{session.id}/tool-grants').json() == []
    assert client.post(f'{root}/sessions/{session.id}/runs', json={'message': 'third'},
                       headers={'Idempotency-Key': 'grant-3'}).status_code in (200, 201, 202)
    run_once(database, 'worker', model_factory=lambda _: _turns('third'), registry_factory=_registry(invoked))
    assert _latest_run(database, session.id).status == 'waiting_approval' and invoked == ['first', 'second']


def test_destructive_tools_cannot_be_remembered(settings_client, database):  # noqa: F811
    client, _, identity, *_ = settings_client
    principal, tenant, session, run, _ = stack(database, ['write'])
    identity[0] = principal
    invoked = []
    run_once(database, 'worker', model_factory=lambda _: _turns('x'), registry_factory=_registry(invoked, risk='destructive'))
    path = f'/api/v1/tenants/{tenant.id}/native/runs/{run.id}/approvals'
    pending = client.get(path).json()
    assert pending[0]['rememberable'] is False
    assert client.post(f'{path}/{pending[0]["id"]}', json={'approve': True, 'remember': 'session'}).status_code == 422
    assert client.post(f'{path}/{pending[0]["id"]}', json={'approve': True}).status_code == 200


def test_grants_are_bound_to_the_agent_version(database):  # noqa: F811
    from nexus_platform.runs.approvals import grant_for_call
    from nexus_platform.persistence.models import ActionGrantRecord
    from nexus_core.platform import new_id, utc_now
    principal, tenant, session, run, _ = stack(database, ['write'])
    with database() as db, db.begin():
        row = db.get(RunRecord, run.id)
        db.add(ActionGrantRecord(id=new_id(), tenant_id=tenant.id, principal_id=row.principal_id, scope='session',
                                 scope_id=session.id, agent_version_id=UUID(row.config_snapshot['agent_version_id']),
                                 tool_name='write', risk='write', created_at=utc_now()))
    with database() as db, db.begin():
        row = db.get(RunRecord, run.id)
        assert grant_for_call(db, row, ToolCall('c', 'write', '{}')) is True
        row.config_snapshot = {**row.config_snapshot, 'agent_version_id': str(new_id())}
        assert grant_for_call(db, row, ToolCall('c', 'write', '{}')) is False


def test_migration_adds_and_removes_action_grants(tmp_path):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, inspect
    url = f'sqlite:///{tmp_path / "grants.db"}'
    config = Config('alembic.ini')
    config.attributes['database_url'] = url
    command.upgrade(config, 'b7c6d5e4f3a2')
    inspector = inspect(create_engine(url))
    assert 'action_grants' in inspector.get_table_names()
    assert {'reason', 'risk'} <= {c['name'] for c in inspector.get_columns('action_approvals')}
    command.downgrade(config, 'a9b8c7d6e5f4')
    assert 'action_grants' not in inspect(create_engine(url)).get_table_names()
