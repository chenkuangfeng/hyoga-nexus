"""Dispatch ledger rules on SQLite: epoch fencing, CAS claims, FIFO, blocking and recovery."""
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from nexus_platform.persistence.base import Base
from nexus_platform.persistence.models.audit import AuditRecord
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


def _enqueue(db, session_id, run_id=None):
    return ledger.enqueue(
        db, session_id=session_id, run_id=run_id or uuid4(), admission_id=uuid4(), now=NOW,
    )


def test_begin_process_increments_epoch_each_start(db):
    assert ledger.current_epoch(db) == 0
    assert ledger.begin_process(db, instance_id="a", now=NOW) == 1
    assert ledger.begin_process(db, instance_id="b", now=NOW) == 2
    assert ledger.current_epoch(db) == 2


def test_superseded_epoch_cannot_claim_or_finish(db):
    old = ledger.begin_process(db, instance_id="old", now=NOW)
    session_id = uuid4()
    admission = _enqueue(db, session_id)
    ledger.claim_next(db, epoch=old, session_id=session_id, now=NOW)
    ledger.begin_process(db, instance_id="new", now=NOW)
    with pytest.raises(ledger.StaleEpoch):
        ledger.claim_next(db, epoch=old, session_id=session_id, now=NOW)
    with pytest.raises(ledger.StaleEpoch):
        ledger.finish(db, epoch=old, admission_id=admission.admission_id, now=NOW)


def test_claims_follow_fifo_order_and_block_until_finished(db):
    epoch = ledger.begin_process(db, instance_id="w", now=NOW)
    session_id = uuid4()
    first = _enqueue(db, session_id)
    second = _enqueue(db, session_id)

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
    head = _enqueue(db, session_id)
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
        _enqueue(db, session_id)
    with pytest.raises(ledger.QueueFull):
        _enqueue(db, session_id)
    # Another session is unaffected by this session's cap.
    _enqueue(db, uuid4())


def test_finish_requires_claiming_epoch(db):
    old = ledger.begin_process(db, instance_id="old", now=NOW)
    session_id = uuid4()
    admission = _enqueue(db, session_id)
    ledger.claim_next(db, epoch=old, session_id=session_id, now=NOW)
    new = ledger.begin_process(db, instance_id="new", now=NOW)
    with pytest.raises(ledger.StaleEpoch):
        ledger.finish(db, epoch=old, admission_id=admission.admission_id, now=NOW)
    # Recovery under the new epoch is what moves the row forward.
    assert ledger.recover_previous_epochs(db, epoch=new, now=NOW) == [admission.run_id]


def test_recovery_marks_older_started_as_unknown_and_blocks(db):
    old = ledger.begin_process(db, instance_id="old", now=NOW)
    session_id = uuid4()
    admission = _enqueue(db, session_id)
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
    _enqueue(db, session_id)
    ledger.claim_next(db, epoch=epoch, session_id=session_id, now=NOW)
    assert ledger.recover_previous_epochs(db, epoch=epoch, now=NOW) == []


def test_resolve_unknown_is_the_only_way_out(db):
    old = ledger.begin_process(db, instance_id="old", now=NOW)
    session_id = uuid4()
    admission = _enqueue(db, session_id)
    ledger.claim_next(db, epoch=old, session_id=session_id, now=NOW)
    new = ledger.begin_process(db, instance_id="new", now=NOW)
    ledger.recover_previous_epochs(db, epoch=new, now=NOW)

    tenant, actor = uuid4(), uuid4()
    ledger.resolve_unknown(db, epoch=new, admission_id=admission.admission_id,
                           tenant_id=tenant, actor_id=actor, now=NOW)
    assert not ledger.session_blocked(db, session_id)
    audit_rows = db.scalars(select(AuditRecord).where(AuditRecord.action == "run.unknown_resolved")).all()
    assert [(row.tenant_id, row.actor_user_id, row.target_id) for row in audit_rows] == [
        (tenant, actor, str(admission.admission_id)),
    ]
    with pytest.raises(ledger.NotUnknown):
        # Resolving again is rejected because the row is no longer unknown.
        ledger.resolve_unknown(db, epoch=new, admission_id=admission.admission_id,
                               tenant_id=tenant, actor_id=actor, now=NOW)


def test_resolve_unknown_rejects_queued_rows(db):
    epoch = ledger.begin_process(db, instance_id="w", now=NOW)
    admission = _enqueue(db, uuid4())
    with pytest.raises(ledger.NotUnknown):
        ledger.resolve_unknown(db, epoch=epoch, admission_id=admission.admission_id,
                               tenant_id=uuid4(), actor_id=uuid4(), now=NOW)


def test_status_check_constraint_rejects_unknown_status(db):
    from sqlalchemy.exc import IntegrityError

    epoch = ledger.begin_process(db, instance_id="w", now=NOW)
    admission = _enqueue(db, uuid4())
    row = db.scalar(select(SessionAdmissionRecord).where(
        SessionAdmissionRecord.admission_id == admission.admission_id,
    ))
    row.status = "bogus"
    with pytest.raises(IntegrityError):
        db.flush()


def test_claim_loser_gets_stale_claim_after_head_changed(tmp_path):
    """Two connections race for the same head: the loser's conditional update matches nothing."""
    engine = create_engine("sqlite:///" + str(tmp_path / "race.db"))
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as setup:
        epoch = ledger.begin_process(setup, instance_id="w", now=NOW)
        session_id = uuid4()
        _enqueue(setup, session_id)
        setup.commit()
    with factory() as first, factory() as second:
        loser_head = ledger.select_head(second, session_id)
        assert ledger.claim_next(first, epoch=epoch, session_id=session_id, now=NOW) is not None
        first.commit()
        with pytest.raises(ledger.StaleClaim):
            ledger.cas_claim(second, loser_head, epoch=epoch, now=NOW)
    engine.dispose()


def test_terminal_run_releases_queued_and_started_but_not_unknown(db):
    from nexus_platform.persistence.models.run import RunRecord
    from nexus_core.platform import RunStatus

    epoch = ledger.begin_process(db, instance_id="w", now=NOW)
    session_id = uuid4()
    first = _enqueue(db, session_id)
    ledger.claim_next(db, epoch=epoch, session_id=session_id, now=NOW)
    second = _enqueue(db, session_id)
    cancelled_queued = _enqueue(db, session_id)

    # Cancelling a queued run must release its FIFO slot, or the queue head would wedge.
    ledger.finish_run(db, run_id=cancelled_queued.run_id, now=NOW)
    row = db.scalar(select(SessionAdmissionRecord).where(
        SessionAdmissionRecord.admission_id == cancelled_queued.admission_id))
    assert row.status == "terminal"

    ledger.finish_run(db, run_id=first.run_id, now=NOW)
    assert ledger.claim_next(db, epoch=epoch, session_id=session_id, now=NOW).admission_id == second.admission_id

    # Unknown is never released by a terminal run write.
    db.flush()
    unknown_epoch = ledger.begin_process(db, instance_id="w2", now=NOW)
    ledger.recover_previous_epochs(db, epoch=unknown_epoch, now=NOW)
    assert ledger.session_blocked(db, session_id)
    ledger.finish_run(db, run_id=second.run_id, now=NOW)
    assert ledger.session_blocked(db, session_id)
