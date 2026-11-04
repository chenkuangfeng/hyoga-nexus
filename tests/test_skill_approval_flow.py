"""Script runs through the real worker: approval waits, approval runs once, rejection never executes.

Proposal 2026-11-04-skill-scripts, tasks 7.5 and 10.1. The model is a FakeModel; the worker, gateway,
approval records and the Run store are the real ones. The gate is opened as in the store tests.
"""
from types import SimpleNamespace
from uuid import UUID

import pytest
from sqlalchemy import select

from nexus_core.runtime import ModelChunk
from nexus_platform.errors import Conflict
from nexus_platform.persistence.models import RunEventRecord
from nexus_platform.runs.approvals import list_pending, resolve
from nexus_platform.runs.service import create_run
from nexus_platform.sessions.service import create_session
from nexus_worker.__main__ import run_once
from test_native_runtime import FakeModel, call, run_row
from test_platform import database  # noqa: F401  (pytest fixture)
from test_skill_script_run import SCRIPT_SKILL, CODE, TOOLS
from test_skills_platform import PRINCIPAL, _agent, _publish, _tenant, _version_for

CALL = '{"name": "greeter", "script": "go", "args": {"text": "approved"}}'


@pytest.fixture
def gate(monkeypatch):
    import nexus_platform.configuration as configuration
    monkeypatch.setattr(configuration, 'skill_scripts_allowed', lambda *a, **k: True)
    monkeypatch.setattr(configuration, 'auth_settings', lambda *a, **k: SimpleNamespace(mode='development'))


def _run(database, key):
    tenant, model_version = _tenant(database)
    published = _publish(database, tenant, text=SCRIPT_SKILL, files={'scripts/go.py': CODE})
    agent_version_id = _version_for(database, tenant, _agent(database, tenant, model_version, [published], tools=TOOLS))
    with database() as db:
        session = create_session(db, PRINCIPAL, tenant.id, agent_version_id=agent_version_id, title='Approve')
        run, _ = create_run(db, PRINCIPAL, tenant.id, session.id, message='Greet', idempotency_key=key)
        return tenant.id, run.id


def _kinds(database, run_id):
    with database() as db:
        return [row.event_type for row in db.scalars(select(RunEventRecord).where(RunEventRecord.run_id == run_id)
                                                     .order_by(RunEventRecord.sequence))]


def test_approved_script_runs_once_and_its_output_reaches_the_model(database, gate):
    tenant_id, run_id = _run(database, 'approve-1')
    model = FakeModel([[call('run_skill_script', CALL)]])
    run_once(database, 'worker', model_factory=lambda _: model)
    assert run_row(database, run_id).status == 'waiting_approval'
    assert 'skill.script.started' not in _kinds(database, run_id)
    with database() as db:
        pending = list_pending(db, PRINCIPAL, tenant_id, run_id)
        assert len(pending) == 1
        approval_id = pending[0]['id']
    with database() as db:
        resolve(db, PRINCIPAL, tenant_id, run_id, UUID(approval_id), approve=True)
    resumed = FakeModel([[_text('done')]])
    run_once(database, 'worker', model_factory=lambda _: resumed)
    assert run_row(database, run_id).status == 'completed'
    kinds = _kinds(database, run_id)
    assert kinds.count('skill.script.started') == 1 and kinds.count('skill.script.completed') == 1
    tool_messages = [m.content for m in resumed.requests[0].messages if m.role == 'tool']
    assert any('hello approved' in text and '<script_output' in text for text in tool_messages)
    with database() as db:
        with pytest.raises(Conflict):
            resolve(db, PRINCIPAL, tenant_id, run_id, UUID(approval_id), approve=True)


def test_rejected_script_never_starts(database, gate):
    tenant_id, run_id = _run(database, 'reject-1')
    run_once(database, 'worker', model_factory=lambda _: FakeModel([[call('run_skill_script', CALL)]]))
    with database() as db:
        approval_id = list_pending(db, PRINCIPAL, tenant_id, run_id)[0]['id']
    with database() as db:
        resolve(db, PRINCIPAL, tenant_id, run_id, UUID(approval_id), approve=False)
    run_once(database, 'worker', model_factory=lambda _: FakeModel([[_text('ok')]]))
    assert run_row(database, run_id).status == 'completed'
    assert 'skill.script.started' not in _kinds(database, run_id)


def _text(text):
    return ModelChunk('text', text=text)
