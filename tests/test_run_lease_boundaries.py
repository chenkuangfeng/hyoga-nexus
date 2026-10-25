"""P1 worker compatibility after extracting transaction-bound Run/queue repositories."""
from unittest.mock import patch
import pytest
from sqlalchemy import func, select
from nexus_core.platform import new_id, utc_now
from nexus_platform.persistence.models import OutboxRecord, RunEventRecord, RunRecord
from nexus_platform.runs.service import claim_next, process_claimed
from test_platform import database
from test_run_write_boundaries import submitted


@pytest.mark.parametrize('status,attempt,expected,error,event_types', [
    ('queued', 0, 'failed', 'runtime_not_configured', ['run.queued', 'run.started', 'run.failed']),
    ('running', 0, 'interrupted', 'worker_lease_expired', ['run.queued', 'run.interrupted']),
    ('queued', 1, 'interrupted', 'worker_lease_expired', ['run.queued', 'run.interrupted']),
])
def test_p1_first_execution_and_uncertain_recovery_are_distinct(database, status, attempt, expected, error, event_types):
    _, _, _, run = submitted(database)
    with database() as db:
        task_id = claim_next(db, 'worker')
    with database() as db, db.begin():
        row = db.get(RunRecord, run.id)
        row.status, row.attempt = status, attempt
    with database() as db:
        assert process_claimed(db, task_id, 'worker')
        assert not db.in_transaction()
    with database() as db:
        row = db.get(RunRecord, run.id)
        assert (row.status, row.error_code) == (expected, error)
        assert row.ended_at is not None
        assert row.attempt == (1 if expected == 'failed' else attempt)
        task = db.get(OutboxRecord, task_id)
        assert task.completed_at is not None
        assert task.lease_owner is None and task.lease_until is None
        assert list(db.scalars(select(RunEventRecord.event_type).order_by(RunEventRecord.sequence))) == event_types


def test_wrong_worker_missing_and_duplicate_deliveries_do_not_execute(database):
    _, _, _, run = submitted(database)
    with database() as db:
        task_id = claim_next(db, 'owner')
        assert not process_claimed(db, task_id, 'stranger')
        assert not process_claimed(db, new_id(), 'owner')
    with database() as db:
        assert db.get(RunRecord, run.id).status == 'queued'
        assert db.scalar(select(func.count()).select_from(RunEventRecord)) == 1
    with database() as db:
        assert process_claimed(db, task_id, 'owner')
        assert not process_claimed(db, task_id, 'owner')
    with database() as db:
        assert db.get(RunRecord, run.id).attempt == 1
        assert db.scalar(select(func.count()).select_from(RunEventRecord)) == 3


@pytest.mark.parametrize('cancel_delivery', [False, True])
def test_cancellation_precedes_execution_recovery(database, cancel_delivery):
    _, _, _, run = submitted(database)
    with database() as db:
        task_id = claim_next(db, 'worker')
    with database() as db, db.begin():
        row = db.get(RunRecord, run.id)
        row.status, row.attempt = 'running', 1
        if cancel_delivery:
            db.get(OutboxRecord, task_id).message_type = 'run.cancel'
        else:
            row.cancel_requested_at = utc_now()
    with database() as db:
        assert process_claimed(db, task_id, 'worker')
    with database() as db:
        row = db.get(RunRecord, run.id)
        assert row.status == 'cancelled'
        assert row.error_code is None
        assert list(db.scalars(select(RunEventRecord.event_type).order_by(RunEventRecord.sequence))) == [
            'run.queued', 'run.cancelled',
        ]


def test_terminal_run_closes_delivery_without_changing_legacy_lease_fields(database):
    _, _, _, run = submitted(database)
    with database() as db:
        task_id = claim_next(db, 'worker')
    with database() as db, db.begin():
        db.get(RunRecord, run.id).status = 'completed'
    with database() as db:
        assert process_claimed(db, task_id, 'worker')
    with database() as db:
        task = db.get(OutboxRecord, task_id)
        assert task.completed_at is not None
        assert task.lease_owner == 'worker' and task.lease_until is not None
        assert db.scalar(select(func.count()).select_from(RunEventRecord)) == 1


def test_processing_failure_rolls_back_started_failed_events_and_delivery(database):
    _, _, _, run = submitted(database)
    with database() as db:
        task_id = claim_next(db, 'worker')
    with database() as db, patch('nexus_platform.runs.audit_repository.audit',
                                 side_effect=RuntimeError('audit offline')):
        with pytest.raises(RuntimeError, match='audit offline'):
            process_claimed(db, task_id, 'worker')
    with database() as db:
        row = db.get(RunRecord, run.id)
        assert (row.status, row.attempt) == ('queued', 0)
        assert row.started_at is None and row.ended_at is None
        task = db.get(OutboxRecord, task_id)
        assert task.completed_at is None and task.lease_owner == 'worker'
        assert db.scalar(select(func.count()).select_from(RunEventRecord)) == 1
    with database() as db:
        assert process_claimed(db, task_id, 'worker')
