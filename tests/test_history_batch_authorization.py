"""Session history authorization is decided once per distinct grant per preparation (P8)."""
import nexus_platform.runs.messages as messages_module
from nexus_core.runtime import ModelChunk
from nexus_platform.authz.resources import revoke_resource_grant
from nexus_platform.persistence.models import RunRecord
from nexus_platform.runs.service import create_run
from nexus_worker.__main__ import run_once

from test_platform import database  # noqa: F401 (pytest fixture)
from test_native_runtime import FakeModel, stack


def test_one_shared_grant_is_checked_once_for_all_runs_of_the_session(database, monkeypatch):
    principal, tenant, session, run, grants = stack(database, ['echo'], shared=True)
    for index in range(3):  # three earlier Runs, all using the same granted tool
        with database() as db:
            create_run(db, principal, tenant.id, session.id, message=f'q{index}', idempotency_key=f'k{index}')
        run_once(database, 'worker', model_factory=lambda _: FakeModel([[ModelChunk('text', text=f'a{index}')]]))
    calls = []
    original = messages_module.authorize_resource
    def counting(*args, **kwargs):
        calls.append(kwargs.get('resource_version_id'))
        return original(*args, **kwargs)
    monkeypatch.setattr(messages_module, 'authorize_resource', counting)
    with database() as db:
        create_run(db, principal, tenant.id, session.id, message='now', idempotency_key='now')
    later = FakeModel([[ModelChunk('text', text='ok')]])
    run_once(database, 'worker', model_factory=lambda _: later)
    # One batch for the preparation and one for the model-start check; independent of the number of Runs.
    assert len(calls) <= 2
    assert 'a2' in [m.content for m in later.requests[0].messages]


def test_revoked_grant_stops_a_run_that_depends_on_it_before_any_model_call(database):
    principal, tenant, session, run, grants = stack(database, ['echo'], shared=True)
    run_once(database, 'worker', model_factory=lambda _: FakeModel([[ModelChunk('text', text='secret answer')]]))
    with database() as db:
        new_run, _ = create_run(db, principal, tenant.id, session.id, message="after", idempotency_key="after")
    with database() as db:
        revoke_resource_grant(db, principal, grants[0].id)
    later = FakeModel([[ModelChunk('text', text='ok')]])
    run_once(database, 'worker', model_factory=lambda _: later)
    assert later.requests == []  # no model input was built from the revoked history
    with database() as db:
        assert db.get(RunRecord, new_run.id).error_code == 'run_authorization_denied'
