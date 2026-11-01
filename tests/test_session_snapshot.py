"""Session snapshot: versioned data-only state, optimistic watermark, refusal of unknown versions."""
import pytest
from sqlalchemy import select

from test_platform import database
from test_native_runtime import stack
from nexus_platform.persistence.models import SessionRecord
from nexus_platform.sessions import snapshot
from nexus_platform.sessions.snapshot import InvalidSnapshot, UnknownSnapshotVersion, WatermarkConflict


def _session_id(database):
    _, _, session, _, _ = stack(database)
    return session.id


def test_new_session_starts_at_watermark_zero_without_snapshot(database):
    session_id = _session_id(database)
    with database() as db:
        assert snapshot.read(db, session_id) == (0, None)


def test_save_advances_watermark_and_round_trips(database):
    session_id = _session_id(database)
    with database() as db:
        with db.begin():
            new = snapshot.save(db, session_id, expected_watermark=0, payload={'budget': {'rounds': 3}, 'notes': ['a']})
    assert new == 1
    with database() as db:
        assert snapshot.read(db, session_id) == (1, {'budget': {'rounds': 3}, 'notes': ['a']})
        row = db.get(SessionRecord, session_id)
        assert row.snapshot_version == snapshot.SNAPSHOT_VERSION


def test_stale_watermark_is_rejected_and_leaves_state_unchanged(database):
    session_id = _session_id(database)
    with database() as db:
        with db.begin():
            snapshot.save(db, session_id, expected_watermark=0, payload={'writer': 'first'})
    with database() as db:
        with pytest.raises(WatermarkConflict):
            with db.begin():
                snapshot.save(db, session_id, expected_watermark=0, payload={'writer': 'second'})
    with database() as db:
        assert snapshot.read(db, session_id) == (1, {'writer': 'first'})


def test_two_writers_from_the_same_watermark_cannot_both_succeed(database):
    session_id = _session_id(database)
    with database() as a, database() as b:
        with a.begin():
            snapshot.save(a, session_id, expected_watermark=0, payload={'writer': 'a'})
        with pytest.raises(WatermarkConflict):
            with b.begin():
                snapshot.save(b, session_id, expected_watermark=0, payload={'writer': 'b'})


@pytest.mark.parametrize('bad', [[1, 2], 'text', None, {'handle': object()}, {'n': float('nan')}])
def test_non_data_payloads_are_refused(database, bad):
    session_id = _session_id(database)
    with database() as db:
        with pytest.raises(InvalidSnapshot):
            with db.begin():
                snapshot.save(db, session_id, expected_watermark=0, payload=bad)
        assert snapshot.read(db, session_id) == (0, None)


def test_oversized_payload_is_refused(database):
    session_id = _session_id(database)
    with database() as db:
        with pytest.raises(InvalidSnapshot):
            with db.begin():
                snapshot.save(db, session_id, expected_watermark=0, payload={'blob': 'x' * (snapshot.MAX_SNAPSHOT_BYTES + 1)})


def test_unknown_stored_version_is_refused_not_guessed(database):
    session_id = _session_id(database)
    with database() as db:
        with db.begin():
            row = db.get(SessionRecord, session_id)
            row.snapshot, row.snapshot_version = {'anything': 1}, 1
    with database() as db:
        with pytest.raises(UnknownSnapshotVersion):
            snapshot.read(db, session_id)


def test_missing_session_is_not_found(database):
    from nexus_platform.errors import NotFound
    import uuid
    with database() as db:
        with pytest.raises(NotFound):
            snapshot.read(db, uuid.uuid4())
