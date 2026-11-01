"""A usable summary replaces the rows it covers in the next Run's model input (P8 windowing)."""
from nexus_core.runtime import ModelChunk
from nexus_platform.persistence.models import MessageRecord
from nexus_platform.runs.summaries import append_summary, effective_summary
from nexus_platform.runs.service import create_run
from nexus_platform.sessions.service import create_session
from nexus_worker.__main__ import run_once

from test_platform import database  # noqa: F401 (pytest fixture)
from test_native_runtime import FakeModel, stack


def _summarize(database, session, tenant, source_run_id, through_sequence, content):
    with database() as db:
        with db.begin():
            append_summary(db, session_id=session.id, tenant_id=tenant.id, source_run_id=source_run_id,
                           through_sequence=through_sequence, content=content)


def test_summary_replaces_covered_rows_and_keeps_later_rows(database):
    principal, tenant, session, run, _ = stack(database)
    first = FakeModel([[ModelChunk('text', text='Answer one')]])
    run_once(database, 'worker', model_factory=lambda _: first)
    with database() as db:
        covered_through = db.query(MessageRecord.sequence).filter(
            MessageRecord.session_id == session.id, MessageRecord.content == 'Answer one').scalar()
    _summarize(database, session, tenant, run.id, covered_through, 'SUMMARY-OF-FIRST-RUN')
    with database() as db:
        second, _ = create_run(db, principal, tenant.id, session.id, message='Second question', idempotency_key='second')
    later = FakeModel([[ModelChunk('text', text='Answer two')]])
    run_once(database, 'worker', model_factory=lambda _: later)
    contents = [m.content for m in later.requests[0].messages]
    assert 'SUMMARY-OF-FIRST-RUN' in contents
    assert 'Answer one' not in contents  # covered by the summary, never materialized
    assert 'Second question' in contents  # rows after the cut are kept


def test_summary_is_ignored_when_a_covered_run_is_no_longer_visible(database):
    principal, tenant, session, run, _ = stack(database)
    first = FakeModel([[ModelChunk('text', text='Answer one')]])
    run_once(database, 'worker', model_factory=lambda _: first)
    with database() as db:
        covered_through = db.query(MessageRecord.sequence).filter(
            MessageRecord.session_id == session.id, MessageRecord.content == 'Answer one').scalar()
    _summarize(database, session, tenant, run.id, covered_through, 'SUMMARY-OF-FIRST-RUN')
    # The summary's source Run must belong to this session's allowed set. A Run from another session is
    # not in that set, so the cut must be ignored and the covered rows must come back.
    with database() as db:
        other_session = create_session(db, principal, tenant.id, agent_version_id=session.agent_version_id)
        other, _ = create_run(db, principal, tenant.id, other_session.id, message='Elsewhere', idempotency_key='other')
        other_session_run = other.id
    # Drain the other session's run first so the next worker pass serves this session.
    run_once(database, 'worker', model_factory=lambda _: FakeModel([[ModelChunk('text', text='Elsewhere answer')]]))
    with database() as db:
        with db.begin():
            summary = effective_summary(db, session.id)
            summary.source_run_id = other_session_run
    with database() as db:
        create_run(db, principal, tenant.id, session.id, message='Second question', idempotency_key='second')
    later = FakeModel([[ModelChunk('text', text='Answer two')]])
    run_once(database, 'worker', model_factory=lambda _: later)
    contents = [m.content for m in later.requests[0].messages]
    assert 'SUMMARY-OF-FIRST-RUN' not in contents
    assert 'Answer one' in contents
