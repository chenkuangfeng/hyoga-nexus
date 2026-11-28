"""History projection: cached raw rows keyed by watermark, authorization applied on every run,
and a fresh execution object per Run."""
import pytest
from sqlalchemy import select


from test_platform import database  # noqa: F401 (pytest fixture)
from test_native_runtime import stack, FakeModel, run_row
from nexus_core.runtime import ModelChunk, ToolResult
from nexus_platform.persistence.models import MessageRecord
from nexus_platform.authz.resources import revoke_resource_grant
from nexus_platform.errors import Forbidden
from nexus_platform.runs.service import create_run
from nexus_platform.runs import preparation
from nexus_tools.builtins import builtins
from nexus_worker import native
from nexus_worker.__main__ import run_once
from test_native_runtime import call, registry


def test_new_message_is_visible_to_the_next_run_and_rows_are_rebuilt(database, monkeypatch):
    principal, tenant, session, run, _ = stack(database)
    builds = []
    original = preparation._message_rows
    monkeypatch.setattr(preparation, '_message_rows', lambda db, sid, *args: builds.append(1) or original(db, sid, *args))
    first = FakeModel([[ModelChunk('text', text='Answer one')]])
    run_once(database, 'worker', model_factory=lambda _: first)
    with database() as db:
        second, _ = create_run(db, principal, tenant.id, session.id, message='Second question', idempotency_key='second')
        second_id = second.id
    later = FakeModel([[ModelChunk('text', text='Answer two')]])
    run_once(database, 'worker', model_factory=lambda _: later)
    contents = [m.content for m in later.requests[0].messages]
    assert contents.index('Answer one') < contents.index('Second question')
    assert run_row(database, second_id).status == 'completed'
    assert len(builds) == 2  # each submission advanced the watermark, so rows were rebuilt, never reused stale


def test_revoked_grant_stops_new_submissions_even_with_cached_history(database):
    principal, tenant, session, run, grants = stack(database, ['echo'], shared=True)
    async def echo(args, context):
        return ToolResult('secret-tool-output')
    first = FakeModel([[call('echo', '{"text":"go"}')], [ModelChunk('text', text='done-A')]])
    run_once(database, 'worker', model_factory=lambda _: first, registry_factory=lambda _: registry(echo))
    with database() as db:
        control, _ = create_run(db, principal, tenant.id, session.id, message='Control', idempotency_key='control')
        control_id = control.id
    before = FakeModel([[ModelChunk('text', text='ok')]])
    run_once(database, 'worker', model_factory=lambda _: before)
    assert any(m.content == 'done-A' for m in before.requests[0].messages)
    assert run_row(database, control_id).status == 'completed'
    with database() as db:
        revoke_resource_grant(db, principal, grants[0].id)
    # The submission path re-checks grants before any cached history is consulted.
    with database() as db:
        with pytest.raises(Forbidden):
            create_run(db, principal, tenant.id, session.id, message='After', idempotency_key='after')


def test_each_run_builds_its_own_engine_and_shares_builtin_definitions(database, monkeypatch):
    engines = []
    original = native.RunOrchestrator
    class Recording(original):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            engines.append(self)
    monkeypatch.setattr(native, 'RunOrchestrator', Recording)
    _, _, _, run_a, _ = stack(database)
    _, _, _, run_b, _ = stack(database)
    for run in (run_a, run_b):
        run_once(database, 'worker', model_factory=lambda _: FakeModel([[ModelChunk('text', text='x')]]))
    assert len(engines) == 2 and engines[0] is not engines[1]
    assert builtins() is builtins()
