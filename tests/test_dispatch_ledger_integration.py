"""Dispatch ledger wired into submission, the worker and terminal Run writes."""
from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import select

from test_native_runtime import FakeModel, run_row, stack
from test_platform import database  # noqa: F401  (fixture)
from nexus_core.platform import RunStatus, utc_now
from nexus_core.runtime import ModelChunk
from nexus_platform.errors import Conflict
from nexus_platform.persistence.models.ledger import SessionAdmissionRecord
from nexus_platform.runs import session_ledger as ledger
from nexus_platform.persistence.models.run import RunRecord
from nexus_platform.persistence.models.tenant import MembershipRecord
from nexus_platform.runs.service import create_run
from nexus_worker.__main__ import run_once, start_process_epoch


def _admission_for(factory, run_id):
    with factory() as db:
        return db.scalar(select(SessionAdmissionRecord).where(SessionAdmissionRecord.run_id == run_id))


def _status(factory, admission_id):
    with factory() as db:
        row = db.scalar(select(SessionAdmissionRecord).where(SessionAdmissionRecord.admission_id == admission_id))
        return row.status


def test_completed_run_releases_its_admission_and_next_run_can_start(database):
    principal, tenant, session, run, _ = stack(database)
    admission = _admission_for(database, run.id)
    assert admission.status == "queued"

    epoch = start_process_epoch(database, 'worker-a')
    run_once(database, 'worker-a', model_factory=lambda _: FakeModel([[ModelChunk('text', text='hi')]]),
             ledger_epoch=epoch)
    assert run_row(database, run.id).status == RunStatus.COMPLETED.value
    assert _status(database, admission.admission_id) == "terminal"

    with database() as db:
        second, _ = create_run(db, principal, tenant.id, session.id, message='again', idempotency_key='second')
        db.commit()
    assert _status(database, _admission_for(database, second.id).admission_id) == "queued"


def test_crash_leaves_started_admission_unknown_and_blocks_submission(database):
    principal, tenant, session, run, _ = stack(database)
    old_epoch = start_process_epoch(database, 'worker-old')
    with database() as db:
        ledger.claim_next(db, epoch=old_epoch, session_id=session.id, now=utc_now())
        db.commit()

    # Restart: the earlier claim is no longer trusted. Lease recovery then ends the Run as
    # interrupted, so nothing is active any more, but the session stays blocked by unknown.
    start_process_epoch(database, 'worker-new')
    admission = _admission_for(database, run.id)
    assert _status(database, admission.admission_id) == "unknown"
    with database() as db:
        db.get(RunRecord, run.id).status = RunStatus.INTERRUPTED.value
        db.commit()
    assert _status(database, admission.admission_id) == "unknown"

    with database() as db:
        with pytest.raises(Conflict, match="unresolved run"):
            create_run(db, principal, tenant.id, session.id, message='blocked', idempotency_key='blocked')
        db.rollback()

    with database() as db:
        actor = db.scalar(select(MembershipRecord.user_id).where(MembershipRecord.tenant_id == tenant.id))
        ledger.resolve_unknown(db, epoch=ledger.current_epoch(db), admission_id=admission.admission_id,
                               tenant_id=tenant.id, actor_id=actor, now=utc_now())
        db.commit()
    with database() as db:
        create_run(db, principal, tenant.id, session.id, message='after', idempotency_key='after')
        db.commit()


def test_superseded_worker_cannot_claim_after_restart(database):
    _, _, session, run, _ = stack(database)
    old_epoch = start_process_epoch(database, 'worker-old')
    start_process_epoch(database, 'worker-new')
    from nexus_worker.native import claim_session_admission

    class _Ctx:
        session_id = session.id
        run_id = run.id

    with pytest.raises(ledger.StaleEpoch):
        claim_session_admission(database, old_epoch, _Ctx())
    assert _status(database, _admission_for(database, run.id).admission_id) == "queued"
