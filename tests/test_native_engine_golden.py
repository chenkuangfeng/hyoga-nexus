"""Golden event-sequence baseline for the Native engine (OpenSpec 2026-11-04-native-engine-split, task 2).

Each scenario runs through the worker entry point and records the ordered event kinds, the terminal
Run status and the tool invocation statuses. The engine refactor must keep every baseline identical;
an intentional behaviour change requires updating GOLDEN together with the OpenSpec change.
Timestamps and identifiers are excluded on purpose.
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from test_platform import database  # noqa: F401  (pytest fixture)
from test_native_runtime import FakeModel, call, registry, run_row, stack
from nexus_core.runtime import ModelChunk, ToolResult
from nexus_platform.persistence.models import ToolInvocationRecord
from nexus_platform.runs.service import list_events
from nexus_worker.__main__ import run_once


def observe(database, principal, tenant, run):
    """Return the comparable shape of one finished Run."""
    with database() as db:
        events = [event.event_type for event in list_events(db, principal, tenant.id, run.id, 0)]
    with database() as db:
        invocations = list(db.scalars(select(ToolInvocationRecord)
            .where(ToolInvocationRecord.run_id == run.id).order_by(ToolInvocationRecord.started_at)))
        statuses = [(row.status, row.error_code) for row in invocations]
    return {'events': events, 'status': run_row(database, run.id).status, 'tools': statuses}


def echo_tool():
    async def echo(args, context):
        return ToolResult(args['text'])
    return registry(echo)


SCENARIOS = {}


def scenario(name):
    def register(fn):
        SCENARIOS[name] = fn
        return fn
    return register


@scenario('text_answer')
def _text_answer(database):
    principal, tenant, _, run, _ = stack(database, ['echo'])
    model = FakeModel([[ModelChunk('text', text='Done')]])
    run_once(database, 'worker', model_factory=lambda _: model, registry_factory=lambda _: echo_tool())
    return observe(database, principal, tenant, run)


@scenario('multi_tool_then_answer')
def _multi_tool(database):
    principal, tenant, _, run, _ = stack(database, ['echo'])
    model = FakeModel([[call('echo', '{"text":"a"}'), call('echo', '{"text":"b"}')],
                       [ModelChunk('text', text='Finished')]])
    run_once(database, 'worker', model_factory=lambda _: model, registry_factory=lambda _: echo_tool())
    return observe(database, principal, tenant, run)


@scenario('invalid_arguments_then_answer')
def _invalid_arguments(database):
    principal, tenant, _, run, _ = stack(database, ['echo'])
    model = FakeModel([[call('echo', '{bad'), call('echo', '{"text":"ok"}')],
                       [ModelChunk('text', text='Finished')]])
    run_once(database, 'worker', model_factory=lambda _: model, registry_factory=lambda _: echo_tool())
    return observe(database, principal, tenant, run)


@scenario('truncated_tool_call_then_answer')
def _truncated(database):
    principal, tenant, _, run, _ = stack(database, ['echo'])

    async def truncated_turn():
        yield call('echo', '{"text":"cut')
        yield ModelChunk('done', finish_reason='length')
    model = FakeModel([truncated_turn, [ModelChunk('text', text='Finished')]])
    run_once(database, 'worker', model_factory=lambda _: model, registry_factory=lambda _: echo_tool())
    return observe(database, principal, tenant, run)


@scenario('empty_response_retry_then_answer')
def _empty_retry(database):
    principal, tenant, _, run, _ = stack(database, ['echo'])
    model = FakeModel([[ModelChunk('text', text='')], [ModelChunk('text', text='Finished')]])
    run_once(database, 'worker', model_factory=lambda _: model, registry_factory=lambda _: echo_tool())
    return observe(database, principal, tenant, run)


@scenario('waiting_input')
def _waiting_input(database):
    principal, tenant, _, run, _ = stack(database, ['ask_user'])
    model = FakeModel([[call('ask_user', '{"question":"Which market?"}')]])
    run_once(database, 'worker', model_factory=lambda _: model)
    return observe(database, principal, tenant, run)


# Recorded on main before the engine split (commit d32b48d). Do not edit to match a refactor;
# a mismatch means observable behaviour changed. The one deliberate change since: a turn that produced text
# also stores `message.completed` right after `model.completed` (openspec 2026-11-07-run-event-streaming).
GOLDEN = {
    'empty_response_retry_then_answer': {
        'events': ['run.queued', 'run.started', 'turn.started', 'model.started',
                   'message.delta', 'model.completed', 'model.recovery',
                   'turn.completed', 'turn.started', 'model.started', 'message.delta',
                   'model.completed', 'message.completed', 'turn.completed', 'run.completed'],
        'status': 'completed', 'tools': []},
    'invalid_arguments_then_answer': {
        'events': ['run.queued', 'run.started', 'turn.started', 'model.started',
                   'model.completed', 'tool.started', 'tool.failed', 'tool.started',
                   'tool.completed', 'turn.completed', 'turn.started', 'model.started',
                   'message.delta', 'model.completed', 'message.completed', 'turn.completed',
                   'run.completed'],
        'status': 'completed', 'tools': [('failed', 'tool_arguments_truncated'), ('completed', None)]},
    'multi_tool_then_answer': {
        'events': ['run.queued', 'run.started', 'turn.started', 'model.started',
                   'model.completed', 'tool.started', 'tool.completed', 'tool.started',
                   'tool.completed', 'turn.completed', 'turn.started', 'model.started',
                   'message.delta', 'model.completed', 'message.completed', 'turn.completed',
                   'run.completed'],
        'status': 'completed', 'tools': [('completed', None), ('completed', None)]},
    'text_answer': {
        'events': ['run.queued', 'run.started', 'turn.started', 'model.started',
                   'message.delta', 'model.completed', 'message.completed', 'turn.completed',
                   'run.completed'],
        'status': 'completed', 'tools': []},
    'truncated_tool_call_then_answer': {
        'events': ['run.queued', 'run.started', 'turn.started', 'model.started',
                   'model.completed', 'turn.completed', 'turn.started', 'model.started',
                   'message.delta', 'model.completed', 'message.completed', 'turn.completed',
                   'run.completed'],
        'status': 'completed', 'tools': []},
    'waiting_input': {
        'events': ['run.queued', 'run.started', 'turn.started', 'model.started',
                   'model.completed', 'tool.started', 'tool.completed', 'turn.completed',
                   'input.requested', 'run.waiting_input'],
        'status': 'waiting_input', 'tools': [('completed', None)]},
}


@pytest.mark.parametrize('name', sorted(SCENARIOS))
def test_engine_event_sequence_matches_baseline(database, name):
    observed = SCENARIOS[name](database)
    assert observed == GOLDEN[name], f'{name} observed={observed!r}'


def test_model_events_record_request_estimate_and_run_total(database):
    principal, tenant, _, run, _ = stack(database, ['echo'])
    model = FakeModel([[ModelChunk('text', text='Done')]])
    run_once(database, 'worker', model_factory=lambda _: model)
    with database() as db:
        events = list_events(db, principal, tenant.id, run.id, 0)
    started = next(event for event in events if event.event_type == 'model.started')
    completed = next(event for event in events if event.event_type == 'model.completed')
    assert started.payload['input_estimate_tokens'] > 0
    assert completed.payload['request_input_estimate_tokens'] == started.payload['input_estimate_tokens']
    assert completed.payload['run_total_tokens'] == completed.payload['tokens']
