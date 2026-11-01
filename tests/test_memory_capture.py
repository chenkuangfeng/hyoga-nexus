"""Automatic memory capture (openspec 2026-11-01-memory-optimization, stage 3).

Pure rules: cadence, topic split, backoff, output validation. Platform: default-off enqueue, one
unfinished job per owner, step-by-step state machine with crash/retry checks, leases, and that
capture only creates drafts through the normal propose path. Extraction is scripted (no model).
"""
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from nexus_core.platform import utc_now
from nexus_memory import capture as rules
from nexus_memory import service as memory_rules
from nexus_memory.ports import MemoryConflict
from nexus_platform.memory import capture
from nexus_platform.persistence.models import (
    MemoryCaptureJobRecord,
    MemoryDraftRecord,
    MessageRecord,
    RunRecord,
)

from test_native_runtime import stack
from test_platform import database  # noqa: F401 (pytest fixture)

T0 = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)


def msg(sequence, minutes=0, role='user', content='x'):
    return rules.Message(sequence=sequence, role=role, content=content, created_at=T0 + timedelta(minutes=minutes))


# ---------------------------------------------------------------- pure rules

def test_topics_split_only_after_a_gap_of_an_hour():
    topics = rules.split_topics([msg(1, 0), msg(2, 30), msg(3, 90), msg(4, 95)])
    assert [[m.sequence for m in t] for t in topics] == [[1, 2], [3, 4]]


def test_window_takes_first_topic_capped_at_forty_and_respects_cursor():
    messages = [msg(i, 0) for i in range(1, 51)]
    window = rules.plan_window(messages, cursor=0, now=T0, last_window_at=None)
    assert (window.from_sequence, window.through_sequence, len(window.messages)) == (1, 40, 40)
    later = rules.plan_window(messages, cursor=40, now=T0, last_window_at=None)
    assert (later.from_sequence, later.through_sequence) == (41, 50)
    assert rules.plan_window(messages, cursor=50, now=T0, last_window_at=None) is None


def test_window_waits_for_the_minimum_interval_since_the_last_window():
    messages = [msg(1, 0)]
    assert rules.plan_window(messages, cursor=0, now=T0, last_window_at=T0 - timedelta(seconds=299)) is None
    assert rules.plan_window(messages, cursor=0, now=T0, last_window_at=T0 - timedelta(seconds=300)) is not None


def test_backoff_doubles_and_is_capped():
    assert [rules.backoff_seconds(n) for n in (1, 2, 3)] == [120, 240, 480]
    assert rules.backoff_seconds(20) == 3600
    with pytest.raises(ValueError):
        rules.backoff_seconds(0)


def test_invalid_output_is_discarded_and_counted_not_stored():
    raw = [
        {'op': 'add', 'kind': 'memory', 'diff': 'use checklist'},
        {'op': 'drop_table'},
        'not an object',
        {'op': 'add', 'diff': '   '},
        {'op': 'add', 'kind': 'secret', 'diff': 'x'},
        {'op': 'none'},
        {'op': 'delete', 'entry_id': str(uuid4())},
    ]
    verdict = rules.validate_actions(raw, unattended=True)
    assert verdict.actions == [{'op': 'add', 'kind': 'memory', 'diff': 'use checklist'}]
    assert verdict.rejected == 5
    assert 'unknown_op' in verdict.reasons and 'unattended_op_not_allowed' in verdict.reasons
    # Attended, a delete is recognized but still not stored in this stage.
    delete = [{'op': 'delete', 'entry_id': str(uuid4())}]
    attended = rules.validate_actions(delete, unattended=False)
    assert attended.actions == [] and attended.reasons == ['delete_not_supported']


def test_unattended_runs_may_only_add():
    entry = str(uuid4())
    update = {'op': 'update', 'entry_id': entry, 'base_version': 1, 'diff': 'new text'}
    assert rules.validate_actions([update], unattended=True).actions == []
    attended = rules.validate_actions([update], unattended=False).actions
    assert attended and attended[0]['base_version'] == 1


def test_non_list_output_is_rejected_as_a_whole():
    verdict = rules.validate_actions({'op': 'add', 'diff': 'x'}, unattended=True)
    assert verdict.actions == [] and verdict.reasons == ['not_a_list']


# ---------------------------------------------------------------- platform

def _messages(factory, session_id, count, *, created=None):
    """Append `count` messages after the session's current highest sequence."""
    created = created or utc_now() - timedelta(hours=2)
    with factory() as db:
        with db.begin():
            start = (db.scalar(select(func.max(MessageRecord.sequence)).where(
                MessageRecord.session_id == session_id)) or 0) + 1
            for n in range(start, start + count):
                db.add(MessageRecord(id=uuid4(), session_id=session_id, sequence=n,
                                     role='user' if n % 2 else 'assistant',
                                     content=f'message {n} about deployment checklist',
                                     runtime_metadata={}, created_at=created + timedelta(seconds=n)))


def _enable(factory, principal, tenant_id, enabled=True):
    with factory() as db:
        return capture.set_capture(db, principal, tenant_id, enabled=enabled,
                                   model_profile_version_id=uuid4() if enabled else None)


def _enqueue(factory, run_id, now):
    with factory() as db:
        with db.begin():
            run = db.get(RunRecord, run_id)
            return capture.enqueue_for_run(db, run, now=now)


def _job(factory, job_id):
    with factory() as db:
        job = db.get(MemoryCaptureJobRecord, job_id)
        return {'state': job.state, 'attempts': job.attempt_count, 'stored': job.stored_count,
                'error': job.last_error, 'actions': job.actions, 'available_at': job.available_at,
                'next_retry_at': job.next_retry_at}


def _drafts(factory, run):
    with factory() as db:
        return [(d.origin, d.diff, d.status) for d in db.query(MemoryDraftRecord).filter(
            MemoryDraftRecord.tenant_id == run.tenant_id)]


def _scripted(outputs):
    """Extractor that returns the scripted outputs in order and records each call."""
    calls = []

    def extractor(*, messages, related):
        calls.append(len(messages))
        item = outputs[len(calls) - 1] if len(calls) <= len(outputs) else outputs[-1]
        if isinstance(item, Exception):
            raise item
        return item
    extractor.calls = calls
    return extractor


def test_capture_is_off_by_default_and_queues_nothing(database):  # noqa: F811
    _, _, session, run, _ = stack(database)
    _messages(database, session.id, 4)
    assert _enqueue(database, run.id, utc_now()) is None
    with database() as db:
        assert db.query(MemoryCaptureJobRecord).count() == 0


def test_enabling_requires_a_capture_model(database):  # noqa: F811
    principal, tenant, _, _, _ = stack(database)
    with database() as db:
        with pytest.raises(ValueError):
            capture.set_capture(db, principal, tenant.id, enabled=True, model_profile_version_id=None)
        assert capture.capture_settings(db, principal, tenant.id) == {'enabled': False,
                                                                     'model_profile_version_id': None}


def test_enabled_owner_gets_one_unfinished_job_at_a_time(database):  # noqa: F811
    principal, tenant, session, run, _ = stack(database)
    _messages(database, session.id, 4)
    _enable(database, principal, tenant.id)
    job_id = _enqueue(database, run.id, utc_now())
    assert job_id is not None
    assert _job(database, UUID(job_id))['state'] == 'pending'
    # Another completed Run while the job is unfinished queues nothing; its messages stay unread.
    _messages(database, session.id, 2)
    assert _enqueue(database, run.id, utc_now()) is None


def test_full_run_creates_capture_drafts_through_propose_and_completes(database):  # noqa: F811
    principal, tenant, session, run, _ = stack(database)
    _messages(database, session.id, 4)
    _enable(database, principal, tenant.id)
    job_id = UUID(_enqueue(database, run.id, utc_now()))
    extractor = _scripted([[{'op': 'add', 'kind': 'memory', 'diff': 'Deploy with checklist'},
                            {'op': 'add', 'kind': 'memory', 'diff': 'Deploy with checklist'}]])
    later = utc_now() + timedelta(hours=1)
    assert capture.run_due(database, extractor, worker_id='w1', now=later) == 'completed'
    assert extractor.calls == [5]  # the stack writes one message, then four were appended
    drafts = _drafts(database, run)
    # The second identical action is a duplicate of the first pending draft, so only one draft exists.
    assert drafts == [('capture', 'Deploy with checklist', 'pending_review')]
    state = _job(database, job_id)
    assert state['state'] == 'completed' and state['stored'] == 2


def test_capture_model_is_called_without_tools_and_gets_the_window(database):  # noqa: F811
    principal, tenant, session, run, _ = stack(database)
    _messages(database, session.id, 3)
    _enable(database, principal, tenant.id)
    _enqueue(database, run.id, utc_now())
    seen = {}

    def extractor(**kwargs):
        # The extraction contract has exactly these keyword arguments: no tool definitions can be passed.
        seen['keys'] = sorted(kwargs)
        return []
    capture.run_due(database, extractor, worker_id='w1', now=utc_now() + timedelta(hours=1))
    assert seen['keys'] == ['messages', 'related']


def test_crash_after_extraction_does_not_call_the_model_again(database, monkeypatch):  # noqa: F811
    principal, tenant, session, run, _ = stack(database)
    _messages(database, session.id, 4)
    _enable(database, principal, tenant.id)
    job_id = UUID(_enqueue(database, run.id, utc_now()))
    extractor = _scripted([[{'op': 'add', 'kind': 'memory', 'diff': 'Alpha fact'}]])
    now = utc_now() + timedelta(hours=1)
    real = memory_rules.propose

    def crash(*args, **kwargs):
        raise RuntimeError('simulated crash while storing')
    monkeypatch.setattr(memory_rules, 'propose', crash)
    assert capture.run_due(database, extractor, worker_id='w1', now=now) == 'extracted'
    assert _job(database, job_id)['attempts'] == 1 and _job(database, job_id)['error'] == 'step_error'
    assert _drafts(database, run) == []
    # Backoff: not due yet, so a run at the same moment does nothing.
    assert capture.run_due(database, extractor, worker_id='w1', now=now) is None
    monkeypatch.setattr(memory_rules, 'propose', real)
    later = now + timedelta(hours=1)
    assert capture.run_due(database, extractor, worker_id='w1', now=later) == 'completed'
    assert extractor.calls == [5]  # extraction happened once
    assert _drafts(database, run) == [('capture', 'Alpha fact', 'pending_review')]


def test_crash_mid_store_rolls_back_and_retry_creates_no_duplicates(database, monkeypatch):  # noqa: F811
    principal, tenant, session, run, _ = stack(database)
    _messages(database, session.id, 4)
    _enable(database, principal, tenant.id)
    _enqueue(database, run.id, utc_now())
    extractor = _scripted([[{'op': 'add', 'kind': 'memory', 'diff': 'First fact'},
                            {'op': 'add', 'kind': 'memory', 'diff': 'Second fact'}]])
    real = memory_rules.propose
    calls = {'n': 0}

    def fail_second(*args, **kwargs):
        calls['n'] += 1
        if calls['n'] == 2:
            raise RuntimeError('simulated crash between drafts')
        return real(*args, **kwargs)
    monkeypatch.setattr(memory_rules, 'propose', fail_second)
    now = utc_now() + timedelta(hours=1)
    assert capture.run_due(database, extractor, worker_id='w1', now=now) == 'extracted'
    assert _drafts(database, run) == []  # the first draft was rolled back with the step
    monkeypatch.setattr(memory_rules, 'propose', real)
    assert capture.run_due(database, extractor, worker_id='w1', now=now + timedelta(hours=1)) == 'completed'
    assert sorted(d for _, d, _ in _drafts(database, run)) == ['First fact', 'Second fact']


def test_repeated_failures_stop_at_max_attempts_with_a_stable_code(database):  # noqa: F811
    principal, tenant, session, run, _ = stack(database)
    _messages(database, session.id, 4)
    _enable(database, principal, tenant.id)
    job_id = UUID(_enqueue(database, run.id, utc_now()))
    extractor = _scripted([RuntimeError('provider said something secret')])
    now = utc_now() + timedelta(hours=1)
    for _ in range(rules.MAX_ATTEMPTS + 1):
        capture.run_due(database, extractor, worker_id='w1', now=now)
        now += timedelta(days=1)
    assert len(extractor.calls) == rules.MAX_ATTEMPTS  # never more model calls than attempts
    with database() as db:
        job = db.get(MemoryCaptureJobRecord, job_id)
        assert job.state == 'failed' and job.last_error == 'step_error'
        assert 'secret' not in (job.last_error or '')


def test_lease_blocks_a_second_worker_until_it_expires(database):  # noqa: F811
    principal, tenant, session, run, _ = stack(database)
    _messages(database, session.id, 4)
    _enable(database, principal, tenant.id)
    job_id = UUID(_enqueue(database, run.id, utc_now()))
    now = utc_now() + timedelta(hours=1)
    with database() as db:
        with db.begin():
            assert capture.claim_next(db, worker_id='a', now=now) == job_id
    with database() as db:
        with db.begin():
            assert capture.claim_next(db, worker_id='b', now=now) is None
    with database() as db:
        with db.begin():
            assert capture.claim_next(db, worker_id='b', now=now + capture.LEASE + timedelta(seconds=1)) == job_id
