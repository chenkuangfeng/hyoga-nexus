"""Token usage ledger, reports and monthly limits (openspec 2026-11-11-enterprise-saas E6)."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from nexus_api.dependencies.platform import get_database_session, get_principal
from nexus_api.main import app
from nexus_core.platform import Principal, TenantRole, new_id, utc_now
from nexus_platform.agents import access as agent_access
from nexus_platform.persistence.models import RunEventRecord, RunRecord, UsageLedgerRecord
from nexus_platform.runs.compatibility import create_run
from nexus_platform.sessions.service import create_session
from nexus_platform.tenants import roles
from nexus_platform.tenants.service import add_member
from nexus_platform.usage import service

from test_platform import create_agent_stack, database  # noqa: F401 (pytest fixture)
from test_tenant_roles import _uid

OWNER = Principal('usage-owner', 'test')
MEMBER = Principal('usage-member', 'test')


@pytest.fixture
def stack(database):
    tenant, _, _, agent, version, session = create_agent_stack(database, OWNER)
    with database() as db:
        add_member(db, OWNER, tenant.id, MEMBER, TenantRole.CONTRIBUTOR)
    with database() as db:
        role = roles.create_role(db, OWNER, tenant.id, 'users', ['agents'], ['agents:read'])
    with database() as db:
        agent_access.set_agent_grants(db, OWNER, tenant.id, role.id, agent.id, ['view', 'run'])
    with database() as db:
        roles.assign_role(db, OWNER, tenant.id, _uid(database, MEMBER), role.id)
    with database() as db:
        member_session = create_session(db, MEMBER, tenant.id, agent_version_id=version.id, title='m')
    return database, tenant.id, session.id, member_session.id


def _finished_run(factory, principal, tid, session_id, key, tokens):
    with factory() as db:
        run, _ = create_run(db, principal, tid, session_id, message='hi', idempotency_key=key)
    with factory() as db, db.begin():
        record = db.get(RunRecord, run.id)
        record.status = 'completed'
        sequence = (db.scalar(select(func.max(RunEventRecord.sequence)).where(RunEventRecord.run_id == run.id)) or 0)
        db.add(RunEventRecord(id=new_id(), run_id=run.id, sequence=sequence + 1, event_type='model.completed',
                              payload={'usage': {'input': tokens, 'output': tokens // 2, 'cache_read': 3}},
                              occurred_at=utc_now()))
    with factory() as db, db.begin():
        assert service.record_run_usage(db, run.id) is True
        assert service.record_run_usage(db, run.id) is False  # added once
    return run.id


def test_ended_runs_join_the_daily_ledger_once(stack):
    factory, tid, owner_session, _ = stack
    _finished_run(factory, OWNER, tid, owner_session, 'a', 100)
    _finished_run(factory, OWNER, tid, owner_session, 'b', 20)
    with factory() as db:
        rows = db.scalars(select(UsageLedgerRecord)).all()
        assert [(row.runs, row.input_tokens, row.output_tokens, row.cache_read_tokens) for row in rows] == [
            (2, 120, 60, 6)]
        assert service.unrecorded_runs(db) == []


def test_limits_refuse_new_runs_once_used_up(stack):
    factory, tid, owner_session, member_session = stack
    with factory() as db:
        service.set_limit(db, OWNER, tid, scope_kind='user', scope_id=_uid(factory, MEMBER), monthly_tokens=100)
    _finished_run(factory, MEMBER, tid, member_session, 'm1', 80)  # 80 + 40 = 120 counted tokens
    with factory() as db:
        with pytest.raises(service.QuotaExhausted):
            create_run(db, MEMBER, tid, member_session, message='more', idempotency_key='m2')
    with factory() as db:  # the owner has no limit of their own
        create_run(db, OWNER, tid, owner_session, message='ok', idempotency_key='o1')
    with factory() as db:
        service.set_limit(db, OWNER, tid, scope_kind='user', scope_id=_uid(factory, MEMBER), monthly_tokens=None)
    with factory() as db:
        service.set_limit(db, OWNER, tid, scope_kind='tenant', scope_id=None, monthly_tokens=50)
    with factory() as db:
        with pytest.raises(service.QuotaExhausted):
            create_run(db, MEMBER, tid, member_session, message='more', idempotency_key='m3')
    with factory() as db:
        with pytest.raises(Exception):
            service.set_limit(db, MEMBER, tid, scope_kind='tenant', scope_id=None, monthly_tokens=10**9)


def test_department_limits_count_the_members_below(stack):
    from nexus_platform.orgs import service as orgs
    factory, tid, _, member_session = stack
    with factory() as db:
        root = orgs.create_unit(db, OWNER, tid, 'Acme').id
    with factory() as db:
        sales = orgs.create_unit(db, OWNER, tid, 'Sales', parent_id=root).id
    with factory() as db:
        orgs.assign_member(db, OWNER, tid, sales, _uid(factory, MEMBER), is_primary=True)
    _finished_run(factory, MEMBER, tid, member_session, 'd1', 100)
    with factory() as db:
        limit = service.set_limit(db, OWNER, tid, scope_kind='org_unit', scope_id=root, monthly_tokens=120)
    assert limit['used_this_month'] == 150
    with factory() as db:
        with pytest.raises(service.QuotaExhausted):
            create_run(db, MEMBER, tid, member_session, message='more', idempotency_key='d2')


def test_reports_for_managers_and_members(stack):
    factory, tid, owner_session, member_session = stack
    _finished_run(factory, OWNER, tid, owner_session, 'r1', 10)
    _finished_run(factory, MEMBER, tid, member_session, 'r2', 30)
    app.state.session_factory = factory

    def override_db():
        with factory() as db:
            yield db

    current = {'principal': OWNER}
    app.dependency_overrides[get_database_session] = override_db
    app.dependency_overrides[get_principal] = lambda: current['principal']
    try:
        with TestClient(app) as client:
            by_user = client.get(f'/api/v1/tenants/{tid}/admin/usage', params={'group_by': 'user'}).json()['items']
            assert sorted(row['input_tokens'] for row in by_user) == [10, 30]
            current['principal'] = MEMBER
            assert client.get(f'/api/v1/tenants/{tid}/admin/usage').status_code == 403
            mine = client.get(f'/api/v1/tenants/{tid}/usage/me').json()['items']
            assert [row['input_tokens'] for row in mine] == [30]
    finally:
        app.dependency_overrides.clear()
        app.state.session_factory = None
