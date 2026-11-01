"""Deployment-wide active-session cap: enforced at submission, never by later Runs of a held session."""
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, update
from sqlalchemy.orm import sessionmaker

from nexus_platform.configuration import DatabaseConfigurationError, DEFAULT_MAX_CONCURRENT_SESSIONS, max_concurrent_sessions
from nexus_platform.errors import SessionCapacityExceeded
from nexus_platform.persistence.base import Base
from nexus_platform.persistence.models.ledger import SessionAdmissionRecord
from nexus_platform.runs import session_ledger
from nexus_platform.runs.admission_repository import SqlAlchemyAdmissionRepository

NOW = datetime(2026, 11, 1, tzinfo=timezone.utc)


@pytest.fixture()
def db(tmp_path):
    engine = create_engine("sqlite:///" + str(tmp_path / "capacity.db"))
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as session:
        yield session
    engine.dispose()


def _enqueue(db, session_id, max_sessions):
    with db.begin():
        return session_ledger.enqueue(db, session_id=session_id, run_id=uuid4(), admission_id=uuid4(),
                                      now=NOW, max_sessions=max_sessions)


def test_new_sessions_are_refused_once_the_cap_is_reached(db):
    a, b, c = uuid4(), uuid4(), uuid4()
    _enqueue(db, a, 2)
    _enqueue(db, b, 2)
    with pytest.raises(session_ledger.CapacityFull):
        _enqueue(db, c, 2)


def test_a_session_already_holding_a_slot_may_queue_more_runs_at_the_cap(db):
    a, b = uuid4(), uuid4()
    _enqueue(db, a, 2)
    _enqueue(db, b, 2)
    _enqueue(db, a, 2)  # second Run of a held session takes no new slot
    assert db.query(SessionAdmissionRecord).filter_by(session_id=a).count() == 2


def test_finished_sessions_release_their_slot(db):
    a, b, c = uuid4(), uuid4(), uuid4()
    _enqueue(db, a, 2)
    _enqueue(db, b, 2)
    with db.begin():
        db.execute(update(SessionAdmissionRecord).where(SessionAdmissionRecord.session_id == a).values(status='terminal'))
    _enqueue(db, c, 2)  # a no longer holds work, so c fits
    assert db.query(SessionAdmissionRecord).filter_by(session_id=c).count() == 1


def test_no_cap_when_max_sessions_is_not_given(db):
    for _ in range(5):
        _enqueue(db, uuid4(), None)


def test_repository_maps_cap_to_503_capacity_error(db):
    with db.begin():
        repo = SqlAlchemyAdmissionRepository(db, max_sessions=1)
        repo.enqueue(uuid4(), uuid4(), NOW)
    with pytest.raises(SessionCapacityExceeded) as caught:
        with db.begin():
            SqlAlchemyAdmissionRepository(db, max_sessions=1).enqueue(uuid4(), uuid4(), NOW)
    assert caught.value.status_code == 503 and caught.value.code == 'session_capacity_exceeded'


def test_config_default_and_explicit_values(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert max_concurrent_sessions() == DEFAULT_MAX_CONCURRENT_SESSIONS
    (tmp_path / 'configs').mkdir()
    (tmp_path / 'configs' / 'nexus.toml').write_text('[platform]\nmax_concurrent_sessions = 3\n')
    assert max_concurrent_sessions() == 3


@pytest.mark.parametrize('body', ['max_concurrent_sessions = 0', 'max_concurrent_sessions = "3"',
                                  'max_concurrent_sessions = true', 'platform = 1'])
def test_invalid_config_fails_closed(tmp_path, monkeypatch, body):
    monkeypatch.chdir(tmp_path)
    (tmp_path / 'configs').mkdir()
    (tmp_path / 'configs' / 'nexus.toml').write_text(('' if body.startswith('platform') else '[platform]\n') + body + '\n')
    with pytest.raises(DatabaseConfigurationError):
        max_concurrent_sessions()
