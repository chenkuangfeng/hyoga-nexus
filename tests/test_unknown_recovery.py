"""Sessions blocked by a lost worker and how they are released (openspec 2026-11-07-worker-concurrency, B)."""
from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from nexus_api.dependencies.platform import get_database_session, get_principal
from nexus_api.main import app
from nexus_core.deployment import DeploymentConfigError
from nexus_core.platform import Principal, new_id, utc_now
from nexus_platform.errors import Conflict, NotFound
from nexus_platform.persistence.models import AuditRecord, ToolInvocationRecord
from nexus_platform.persistence.models.ledger import SessionAdmissionRecord
from nexus_platform.persistence.models.schedule import CronJobRecord
from nexus_platform.runs import session_ledger as ledger
from nexus_platform.runs import unknown
from nexus_worker.__main__ import start_process_epoch

from test_native_runtime import stack
from test_platform import database  # noqa: F401 (pytest fixture)


def lose_worker(factory, run, *, tool=None):
    """Leave the Run's admission ``unknown`` the way a crashed worker does: started under an earlier epoch."""
    with factory() as db:
        old = ledger.begin_process(db, instance_id="old", now=utc_now())
        row = db.scalar(select(SessionAdmissionRecord).where(SessionAdmissionRecord.run_id == run.id))
        row.status, row.owner_epoch = "started", old
        if tool:
            db.add(ToolInvocationRecord(id=new_id(), run_id=run.id, operation_id="op1", status="running",
                                        input_summary={"tool_name": tool}, output_summary={}, started_at=utc_now()))
        db.commit()
    start_process_epoch(factory, "new")  # the restart marks the started admission unknown


def admission(factory, run):
    with factory() as db:
        return db.scalar(select(SessionAdmissionRecord).where(SessionAdmissionRecord.run_id == run.id)).status


def lookup(table):
    return table.get


def test_a_lost_worker_leaves_the_session_blocked_until_it_is_released(database):
    principal, tenant, _, run, _ = stack(database)
    lose_worker(database, run)
    assert admission(database, run) == "unknown"
    with database() as db:
        listed = unknown.list_unknown(db, principal, tenant.id)
        assert [row["run_id"] for row in listed] == [run.id]
        result = unknown.resolve_unknown_run(db, principal, tenant.id, run.id)
        assert result["status"] == "terminal"
        again = unknown.resolve_unknown_run(db, principal, tenant.id, run.id)   # idempotent
        assert again["status"] == "terminal"
        assert unknown.list_unknown(db, principal, tenant.id) == []
    with database() as db:
        audits = [row for row in db.scalars(select(AuditRecord)) if row.action == "run.unknown_resolved"]
    assert len(audits) == 1 and audits[0].metadata_["by"] == "user" if hasattr(audits[0], "metadata_") else len(audits) == 1


def test_only_the_runs_owner_and_tenant_admins_may_release_it(database):
    principal, tenant, _, run, _ = stack(database)
    lose_worker(database, run)
    with database() as db:
        from nexus_platform.identity.service import resolve_user
        resolve_user(db, Principal("stranger", "test"))
        with pytest.raises(NotFound):
            unknown.resolve_unknown_run(db, Principal("stranger", "test"), tenant.id, run.id)
        with pytest.raises(NotFound):
            unknown.list_unknown(db, Principal("stranger", "test"), tenant.id)
    assert admission(database, run) == "unknown"


def test_a_run_that_does_not_block_is_a_conflict_not_a_silent_success(database):
    principal, tenant, _, run, _ = stack(database)    # its admission is merely queued
    with database() as db:
        with pytest.raises(Conflict):
            unknown.resolve_unknown_run(db, principal, tenant.id, run.id)


def test_two_callers_cannot_both_release_the_same_block(database):
    principal, tenant, _, run, _ = stack(database)
    lose_worker(database, run)
    with database() as db:
        row = db.scalar(select(SessionAdmissionRecord).where(SessionAdmissionRecord.run_id == run.id))
        first = ledger.resolve_unknown_admin(db, admission_id=row.admission_id, tenant_id=tenant.id,
                                             actor_id=run.principal_id, now=utc_now())
        second = ledger.resolve_unknown_admin(db, admission_id=row.admission_id, tenant_id=tenant.id,
                                              actor_id=run.principal_id, now=utc_now())
        db.commit()
    assert (first, second) == (True, False)


def test_scheduled_sessions_are_released_at_start_up_and_others_are_not(database):
    _, tenant, session, scheduled, _ = stack(database)
    _, _, _, attended, _ = stack(database)
    now = utc_now()
    with database() as db:
        db.add(CronJobRecord(id=new_id(), tenant_id=tenant.id, owner_user_id=scheduled.principal_id,
                             agent_version_id=session.agent_version_id, session_id=session.id, name="job", prompt="x",
                             rule={"kind": "interval", "minutes": 5}, timezone="UTC", state="active",
                             next_run_at=now + timedelta(minutes=5), created_at=now))
        db.commit()
    lose_worker(database, scheduled)    # start-up recovery inside this helper already clears the scheduled one
    lose_worker(database, attended)
    assert admission(database, scheduled) == "terminal"       # nobody is waiting on a scheduled task
    assert admission(database, attended) == "unknown"         # a person's conversation waits for a decision
    with database() as db:
        assert unknown.settle_unattended(db) == []            # nothing left to clear: idempotent


def test_the_safe_release_clears_only_runs_with_no_unfinished_side_effects(database):
    _, _, _, harmless, _ = stack(database)
    _, _, _, risky, _ = stack(database)
    _, _, _, unfamiliar, _ = stack(database)
    lose_worker(database, harmless, tool="read_only_tool")
    lose_worker(database, risky, tool="writes_somewhere")
    lose_worker(database, unfamiliar, tool="mystery")
    table = {"read_only_tool": False, "writes_somewhere": True}   # "mystery" is not known
    with database() as db:
        cleared = unknown.settle_safe(db, lookup(table))
        db.commit()
    assert cleared == [harmless.id]
    assert admission(database, harmless) == "terminal"
    assert admission(database, risky) == admission(database, unfamiliar) == "unknown"
    with database() as db:
        assert unknown.settle_safe(db, None) == []   # without a tool table nothing is provably safe


def test_the_safe_release_setting_is_off_by_default_and_validated(deployment_config):
    deployment_config("")
    assert unknown.auto_resolve_safe_unknown() is False
    deployment_config("[platform]\nauto_resolve_safe_unknown = true\n")
    assert unknown.auto_resolve_safe_unknown() is True
    deployment_config("[platform]\nauto_resolve_safe_unknown = 'yes'\n")
    with pytest.raises(DeploymentConfigError):
        unknown.auto_resolve_safe_unknown()


def test_api_lists_resolves_and_flags_the_blocked_session(database):
    principal, tenant, session, run, _ = stack(database)
    lose_worker(database, run)
    app.state.session_factory = database

    def override():
        with database() as db:
            yield db

    app.dependency_overrides[get_database_session] = override
    app.dependency_overrides[get_principal] = lambda: principal
    try:
        with TestClient(app) as client:
            base = f"/api/v1/tenants/{tenant.id}"
            listed = client.get(base + "/admissions/unknown").json()
            assert [row["run_id"] for row in listed] == [str(run.id)]
            view = client.get(f"{base}/sessions/{session.id}/messages").json()
            assert view["blocked"]["reason"] == "unknown" and view["blocked"]["run_id"] == str(run.id)
            assert client.post(f"{base}/runs/{run.id}/resolve-unknown").status_code == 200
            assert client.get(f"{base}/sessions/{session.id}/messages").json()["blocked"] is None
            assert client.post(f"{base}/runs/{new_id()}/resolve-unknown").status_code == 404
    finally:
        app.dependency_overrides.clear()
        app.state.session_factory = None
