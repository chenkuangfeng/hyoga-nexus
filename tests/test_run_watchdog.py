"""Run watchdog: rules, configuration, durable alerts, acknowledgement and the HTTP surface."""
from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update

from test_platform import database
from test_native_runtime import stack
from nexus_api.dependencies.platform import get_database_session, get_principal
from nexus_api.main import app
from nexus_core.platform import Principal, utc_now
from nexus_core.runtime import ToolCall
from nexus_platform.configuration import DatabaseConfigurationError, watchdog_settings
from nexus_platform.persistence.models.event import RunEventRecord
from nexus_platform.runs.execution import DurableRuntimeStore, prepare_execution
from nexus_platform.runs.service import claim_next
from nexus_platform.runs.watchdog import (ACK_EVENT, ALERT_EVENT, Observation, WatchdogSettings, evaluate,
                                          needs_attention, tool_signature)
from nexus_platform.runs.watchdog_service import acknowledge_watchdog, attention_required

SETTINGS = WatchdogSettings(idle_seconds=300, repeat_threshold=3, interval_seconds=30)


def _observation(**overrides):
    now = utc_now()
    values = dict(status='running', now=now, last_event_at=now, tool_signatures=())
    values.update(overrides)
    return Observation(**values)


# --- Pure rules -----------------------------------------------------------------------------------

def test_idle_rule_fires_only_for_running_runs_past_the_threshold():
    now = utc_now()
    stale = now - timedelta(seconds=301)
    alerts = evaluate(_observation(now=now, last_event_at=stale), SETTINGS)
    assert [(alert.rule, alert.threshold) for alert in alerts] == [('idle', 300)]
    assert evaluate(_observation(now=now, last_event_at=now - timedelta(seconds=300)), SETTINGS) == []
    # Waiting and terminal statuses are never reported, so a person waiting for input is not "idle".
    for status in ('waiting_input', 'waiting_approval', 'queued', 'completed', 'cancelled'):
        assert evaluate(_observation(status=status, now=now, last_event_at=stale), SETTINGS) == []


def test_idle_rule_ignores_runs_without_events_yet():
    assert evaluate(_observation(last_event_at=None), SETTINGS) == []


def test_repeat_rule_needs_consecutive_identical_signatures():
    same = tool_signature('echo', '{"text":"a"}')
    other = tool_signature('echo', '{"text":"b"}')
    assert [a.rule for a in evaluate(_observation(tool_signatures=[same] * 3), SETTINGS)] == ['repeat']
    assert evaluate(_observation(tool_signatures=[same, same, other]), SETTINGS) == []
    # Only the newest window counts: an earlier different call does not block a fresh repeat.
    assert [a.rule for a in evaluate(_observation(tool_signatures=[other, same, same, same]), SETTINGS)] == ['repeat']


def test_tool_signature_depends_on_name_and_arguments_only():
    assert tool_signature('echo', '{"text":"a"}') == tool_signature('echo', '{"text":"a"}')
    assert tool_signature('echo', '{"text":"a"}') != tool_signature('echo', '{"text":"b"}')
    assert tool_signature('echo', '{}') != tool_signature('other', '{}')
    assert len(tool_signature('echo', '{}').split(':')[1]) == 16


@pytest.mark.parametrize(('alert', 'clear', 'expected'), [
    (0, 0, False),
    (5, 0, True),
    (5, 6, False),
    (5, 5, False),
])
def test_attention_is_newer_alert_than_any_clearing_event(alert, clear, expected):
    assert needs_attention(alert, clear) is expected


# --- Configuration --------------------------------------------------------------------------------

def _write(tmp_path, body):
    (tmp_path / 'configs').mkdir(exist_ok=True)
    path = tmp_path / 'configs' / 'nexus.toml'
    path.write_text(body)
    return path


def test_absent_watchdog_section_means_defaults(tmp_path):
    assert watchdog_settings(tmp_path / 'missing.toml') == SETTINGS


def test_explicit_watchdog_values_are_read(tmp_path):
    path = _write(tmp_path, '[watchdog]\nidle_seconds = 600\nrepeat_threshold = 5\ninterval_seconds = 10\n')
    assert watchdog_settings(path) == WatchdogSettings(600, 5, 10)


@pytest.mark.parametrize('body', [
    'idle_seconds = 29',
    'idle_seconds = "300"',
    'repeat_threshold = 1',
    'repeat_threshold = true',
    'interval_seconds = 4',
])
def test_invalid_watchdog_values_fail_closed(tmp_path, body):
    with pytest.raises(DatabaseConfigurationError):
        watchdog_settings(_write(tmp_path, '[watchdog]\n' + body + '\n'))


# --- Durable behaviour ----------------------------------------------------------------------------

def _running_store(database):
    principal, tenant, session, run, _ = stack(database, ['echo'])
    with database() as db:
        task = claim_next(db, 'watchdog-worker')
    context = prepare_execution(database, task, 'watchdog-worker')
    store = DurableRuntimeStore(database, context, 'watchdog-worker', task)
    return principal, tenant, run, store


def _start_calls(store, count, text='a'):
    for index in range(count):
        asyncio.run(store.start(ToolCall(f'call-{index}-{text}-{id(store)}', 'echo', '{"text": "%s"}' % text), None))


def _alerts(database, run_id):
    with database() as db:
        return [row.payload for row in db.scalars(select(RunEventRecord).where(
            RunEventRecord.run_id == run_id, RunEventRecord.event_type == ALERT_EVENT).order_by(RunEventRecord.sequence))]


def test_repeated_tool_calls_alert_once_and_acknowledgement_clears_attention(database):
    principal, tenant, run, store = _running_store(database)
    _start_calls(store, 3)
    alerted: set[str] = set()
    settings = WatchdogSettings(idle_seconds=10**9, repeat_threshold=3, interval_seconds=30)
    store.watch(settings, alerted)
    store.watch(settings, alerted)
    assert alerted == {'repeat'}
    assert _alerts(database, run.id) == [{'rule': 'repeat', 'observed': 3, 'threshold': 3}]
    with database() as db:
        assert attention_required(db, run.id)
    with database() as db:
        acknowledge_watchdog(db, principal, tenant.id, run.id)
        db.commit()
    with database() as db:
        assert not attention_required(db, run.id)
    with database() as db:
        assert db.scalars(select(RunEventRecord.event_type).where(RunEventRecord.run_id == run.id,
                                                                  RunEventRecord.event_type == ACK_EVENT)).all() == [ACK_EVENT]
    # The Run itself is untouched: the watchdog reports, it does not change execution state.
    with database() as db:
        from nexus_platform.persistence.models import RunRecord
        assert db.get(RunRecord, run.id).status == 'running'


def test_recovered_rule_is_reported_again_when_it_stalls_again(database):
    _, _, run, store = _running_store(database)
    _start_calls(store, 3)
    alerted: set[str] = set()
    store.watch(WatchdogSettings(idle_seconds=10**9, repeat_threshold=3, interval_seconds=30), alerted)
    assert alerted == {'repeat'}
    # A stricter threshold means the repetition no longer holds: the episode ends.
    store.watch(WatchdogSettings(idle_seconds=10**9, repeat_threshold=10, interval_seconds=30), alerted)
    assert alerted == set()
    store.watch(WatchdogSettings(idle_seconds=10**9, repeat_threshold=3, interval_seconds=30), alerted)
    assert len(_alerts(database, run.id)) == 2


def test_idle_alert_is_derived_from_the_newest_event_time(database):
    _, _, run, store = _running_store(database)
    with database() as db, db.begin():
        db.execute(update(RunEventRecord).where(RunEventRecord.run_id == run.id)
                   .values(occurred_at=utc_now() - timedelta(hours=1)))
    alerted: set[str] = set()
    store.watch(WatchdogSettings(idle_seconds=300, repeat_threshold=3, interval_seconds=30), alerted)
    alerts = _alerts(database, run.id)
    assert [alert['rule'] for alert in alerts] == ['idle']
    assert alerts[0]['threshold'] == 300 and alerts[0]['observed'] >= 3500


def test_attention_endpoint_reports_and_acknowledges_through_http(database):
    principal, tenant, run, store = _running_store(database)
    _start_calls(store, 3)
    store.watch(WatchdogSettings(idle_seconds=10**9, repeat_threshold=3, interval_seconds=30), set())

    app.state.session_factory = database

    def override_db():
        with database() as db:
            yield db

    app.dependency_overrides[get_database_session] = override_db
    app.dependency_overrides[get_principal] = lambda: principal
    base = f'/api/v1/tenants/{tenant.id}/runs/{run.id}'
    try:
        with TestClient(app) as client:
            assert client.get(base).json()['attention_required'] is True
            response = client.post(base + '/watchdog/acknowledge', headers={'Idempotency-Key': 'ack-1'})
            assert response.status_code == 202
            assert response.json()['attention_required'] is False
            assert client.get(base).json()['attention_required'] is False
    finally:
        app.dependency_overrides.clear()


def test_watchdog_check_failure_does_not_fail_the_run(database, monkeypatch):
    from test_native_runtime import FakeModel, run_row
    from nexus_core.runtime import ModelChunk
    from nexus_platform.runs.store import DurableRuntimeStore
    from nexus_worker.__main__ import run_once
    calls = []

    def broken_watch(self, settings, alerted):
        calls.append(1)
        raise RuntimeError('observation failed')

    monkeypatch.setattr(DurableRuntimeStore, 'watch', broken_watch)
    _, _, _, run, _ = stack(database, ['echo'])
    model = FakeModel([[ModelChunk('text', text='Done')]])
    assert run_once(database, 'worker', model_factory=lambda _: model, watchdog=SETTINGS)
    assert calls, 'the watchdog check should have been attempted'
    assert run_row(database, run.id).status == 'completed'
