"""Dispatch ledger rules on SQLite: epoch fencing, CAS claims, FIFO, blocking and recovery."""
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from nexus_platform.persistence.base import Base
from nexus_platform.persistence.models.ledger import SessionAdmissionRecord
from nexus_platform.runs import session_ledger as ledger

NOW = datetime(2026, 11, 1, tzinfo=UTC)


@pytest.fixture()
def db(tmp_path):
    engine = create_engine("sqlite:///" + str(tmp_path / "ledger.db"))
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as session:
        yield session
    engine.dispose()


def _enqueue(db, epoch, session_id):
    return ledger.enqueue(
        db, epoch=epoch, session_id=session_id, run_id=uuid4(), admission_id=uuid4(), now=NOW,
    )


def test_begin_process_increments_epoch_each_start(db):
    assert ledger.current_epoch(db) == 0
    assert ledger.begin_process(db, instance_id="a", now=NOW) == 1
    assert ledger.begin_process(db, instance_id="b", now=NOW) == 2
    assert ledger.current_epoch(db) == 2


def test_superseded_epoch_cannot_write(db):
    old = ledger.begin_process(db, instance_id="old", now=NOW)
    ledger.begin_process(db, instance_id="new", now=NOW)
    session_id = uuid4()
    with pytest.raises(ledger.StaleEpoch):
        _enqueue(db, old, session_id)
    assert db.scalars(select(SessionAdmissionRecord)).all() == []


def test_claims_follow_fifo_order_and_block_until_finished(db):
    epoch = ledger.begin_process(db, instance_id="w", now=NOW)
    session_id = uuid4()
    first = _enqueue(db, epoch, session_id)
    second = _enqueue(db, epoch, session_id)

    claimed = ledger.claim_next(db, epoch=epoch, session_id=session_id, now=NOW)
    assert claimed.admission_id == first.admission_id
    assert claimed.status == "started"
    assert claimed.owner_epoch == epoch
    # A started admission blocks the session: the second input waits.
    assert ledger.session_blocked(db, session_id)
    assert ledger.claim_next(db, epoch=epoch, session_id=session_id, now=NOW) is None

    ledger.finish(db, epoch=epoch, admission_id=first.admission_id, now=NOW)
    assert not ledger.session_blocked(db, session_id)
    next_claim = ledger.claim_next(db, epoch=epoch, session_id=session_id, now=NOW)
    assert next_claim.admission_id == second.admission_id


def test_claim_is_conditional_on_queued_status(db):
    epoch = ledger.begin_process(db, instance_id="w", now=NOW)
    session_id = uuid4()
    head = _enqueue(db, epoch, session_id)
    # Simulate another writer claiming the head after this one selected it.
    row = db.scalar(select(SessionAdmissionRecord).where(
        SessionAdmissionRecord.admission_id == head.admission_id,
    ))
    row.status = "started"
    db.flush()
    # The head is no longer queued, and the session is blocked by the started row.
    assert ledger.claim_next(db, epoch=epoch, session_id=session_id, now=NOW) is None


def test_queue_cap_rejects_new_admissions(db):
    epoch = ledger.begin_process(db, instance_id="w", now=NOW)
    session_id = uuid4()
    for _ in range(ledger.ADMISSION_QUEUE_MAX):
        _enqueue(db, epoch, session_id)
    with pytest.raises(ledger.QueueFull):
        _enqueue(db, epoch, session_id)
    # Another session is unaffected by this session's cap.
    _enqueue(db, epoch, uuid4())


def test_finish_requires_claiming_epoch(db):
    old = ledger.begin_process(db, instance_id="old", now=NOW)
    session_id = uuid4()
    admission = _enqueue(db, old, session_id)
    ledger.claim_next(db, epoch=old, session_id=session_id, now=NOW)
    new = ledger.begin_process(db, instance_id="new", now=NOW)
    with pytest.raises(ledger.StaleEpoch):
        ledger.finish(db, epoch=old, admission_id=admission.admission_id, now=NOW)
    # Recovery under the new epoch is what moves the row forward.
    assert ledger.recover_previous_epochs(db, epoch=new, now=NOW) == [admission.run_id]


def test_recovery_marks_older_started_as_unknown_and_blocks(db):
    old = ledger.begin_process(db, instance_id="old", now=NOW)
    session_id = uuid4()
    admission = _enqueue(db, old, session_id)
    ledger.claim_next(db, epoch=old, session_id=session_id, now=NOW)

    new = ledger.begin_process(db, instance_id="new", now=NOW)
    assert ledger.recover_previous_epochs(db, epoch=new, now=NOW) == [admission.run_id]
    row = db.scalar(select(SessionAdmissionRecord).where(
        SessionAdmissionRecord.admission_id == admission.admission_id,
    ))
    assert row.status == "unknown"
    # Never replayed: the session stays blocked and nothing new is claimed.
    assert ledger.session_blocked(db, session_id)
    assert ledger.claim_next(db, epoch=new, session_id=session_id, now=NOW) is None


def test_recovery_leaves_current_epoch_rows_alone(db):
    epoch = ledger.begin_process(db, instance_id="w", now=NOW)
    session_id = uuid4()
    _enqueue(db, epoch, session_id)
    ledger.claim_next(db, epoch=epoch, session_id=session_id, now=NOW)
    assert ledger.recover_previous_epochs(db, epoch=epoch, now=NOW) == []


def test_resolve_unknown_is_the_only_way_out(db):
    old = ledger.begin_process(db, instance_id="old", now=NOW)
    session_id = uuid4()
    admission = _enqueue(db, old, session_id)
    ledger.claim_next(db, epoch=old, session_id=session_id, now=NOW)
    new = ledger.begin_process(db, instance_id="new", now=NOW)
    ledger.recover_previous_epochs(db, epoch=new, now=NOW)

    ledger.resolve_unknown(db, epoch=new, admission_id=admission.admission_id, now=NOW)
    assert not ledger.session_blocked(db, session_id)
    with pytest.raises(ledger.StaleEpoch):
        # Resolving again is rejected because the row is no longer unknown.
        ledger.resolve_unknown(db, epoch=new, admission_id=admission.admission_id, now=NOW)


def test_resolve_unknown_rejects_queued_rows(db):
    epoch = ledger.begin_process(db, instance_id="w", now=NOW)
    admission = _enqueue(db, epoch, uuid4())
    with pytest.raises(ledger.StaleEpoch):
        ledger.resolve_unknown(db, epoch=epoch, admission_id=admission.admission_id, now=NOW)


def test_status_check_constraint_rejects_unknown_status(db):
    from sqlalchemy.exc import IntegrityError

    epoch = ledger.begin_process(db, instance_id="w", now=NOW)
    admission = _enqueue(db, epoch, uuid4())
    row = db.scalar(select(SessionAdmissionRecord).where(
        SessionAdmissionRecord.admission_id == admission.admission_id,
    ))
    row.status = "bogus"
    with pytest.raises(IntegrityError):
        db.flush()
