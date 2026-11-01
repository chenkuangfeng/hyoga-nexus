"""Terminal snapshot and unfinished tool calls, written by the Run completion path."""
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select

from test_platform import database
from test_native_runtime import stack
from nexus_core.runtime import RuntimeOutcome
from nexus_platform.persistence.models import RunRecord, ToolInvocationRecord
from nexus_platform.runs.completion import _finish
from nexus_platform.sessions import snapshot


def _finish_run(database, status, error_code=None, running_call=False):
    _, _, session, run, _ = stack(database)
    with database() as db:
        with db.begin():
            row = db.get(RunRecord, run.id)
            row.status = 'running'
            if running_call:
                db.add(ToolInvocationRecord(id=uuid4(), run_id=run.id, operation_id='call-1', status='running',
                    input_summary={}, output_summary={}, started_at=datetime.now(timezone.utc)))
            _finish(db, row, RuntimeOutcome(status, error_code))
    return session.id, run.id


@pytest.mark.parametrize('status,error_code', [('completed', None), ('failed', 'model_timeout'),
                                                ('cancelled', 'cancelled'), ('interrupted', 'worker_lease_expired')])
def test_terminal_outcome_saves_v2_snapshot(database, status, error_code):
    session_id, run_id = _finish_run(database, status, error_code)
    with database() as db:
        watermark, data = snapshot.read(db, session_id)
    assert watermark == 2  # initial message from stack() + terminal save
    assert data == {'last_run': {'id': str(run_id), 'status': status, 'error_code': error_code}}


def test_waiting_state_saves_no_snapshot(database):
    _, _, session, run, _ = stack(database)
    with database() as db:
        with db.begin():
            row = db.get(RunRecord, run.id)
            row.status = 'running'
            _finish(db, row, RuntimeOutcome('waiting_input', None, question='Which market?', candidates=['A']))
    with database() as db:
        watermark, data = snapshot.read(db, session.id)
    assert data is None and watermark == 1  # only the initial message advanced the session


def test_terminal_save_keeps_other_snapshot_keys(database):
    _, _, session, run, _ = stack(database)
    with database() as db:
        with db.begin():
            snapshot.save(db, session.id, expected_watermark=1, payload={'memo': 'kept'})
    with database() as db:
        with db.begin():
            row = db.get(RunRecord, run.id)
            row.status = 'running'
            _finish(db, row, RuntimeOutcome('completed', None))
    with database() as db:
        watermark, data = snapshot.read(db, session.id)
    assert watermark == 3
    assert data['memo'] == 'kept' and data['last_run']['status'] == 'completed'


def test_unfinished_tool_call_is_marked_interrupted(database):
    session_id, run_id = _finish_run(database, 'cancelled', 'cancelled', running_call=True)
    with database() as db:
        call = db.scalar(select(ToolInvocationRecord).where(ToolInvocationRecord.run_id == run_id))
        assert (call.status, call.error_code) == ('interrupted', 'interrupted')
        assert call.ended_at is not None
