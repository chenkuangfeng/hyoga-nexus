"""Append-only context summaries (P11): chain semantics and the migration that introduces them."""
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, select, text

from nexus_platform.persistence.models import ContextSummaryRecord
from nexus_platform.runs.summaries import append_summary, effective_summary

from test_platform import database  # noqa: F401 (pytest fixture)
from test_native_runtime import stack


def test_each_summary_supersedes_the_previous_and_rows_are_kept(database):
    principal, tenant, session, run, _ = stack(database)
    with database() as db:
        with db.begin():
            first = append_summary(db, session_id=session.id, tenant_id=tenant.id, source_run_id=run.id,
                                   through_sequence=4, content='first')
            first_id = first.id
    with database() as db:
        with db.begin():
            second = append_summary(db, session_id=session.id, tenant_id=tenant.id, source_run_id=run.id,
                                    through_sequence=9, content='second')
            second_id, supersedes = second.id, second.supersedes_id
    with database() as db:
        assert supersedes == first_id
        assert effective_summary(db, session.id).content == 'second'
        rows = db.scalars(select(ContextSummaryRecord).where(ContextSummaryRecord.session_id == session.id)).all()
        assert {row.content for row in rows} == {'first', 'second'}  # the first row is retained, not overwritten
        assert {row.id for row in rows} == {first_id, second_id}


def test_a_summary_that_does_not_move_the_cut_point_forward_is_not_written(database):
    principal, tenant, session, run, _ = stack(database)
    with database() as db:
        with db.begin():
            append_summary(db, session_id=session.id, tenant_id=tenant.id, source_run_id=run.id,
                           through_sequence=9, content='latest')
    with database() as db:
        with db.begin():
            written = append_summary(db, session_id=session.id, tenant_id=tenant.id, source_run_id=run.id,
                                     through_sequence=3, content='stale')
            assert written is None
    with database() as db:
        assert effective_summary(db, session.id).content == 'latest'
        assert db.query(ContextSummaryRecord).filter_by(session_id=session.id).count() == 1


def test_content_is_bounded_before_storage(database):
    principal, tenant, session, run, _ = stack(database)
    with database() as db:
        with db.begin():
            record = append_summary(db, session_id=session.id, tenant_id=tenant.id, source_run_id=run.id,
                                    through_sequence=1, content='x' * 20000)
            assert len(record.content) == 8000


def test_migration_keeps_existing_summaries_and_downgrade_keeps_the_effective_one(tmp_path, monkeypatch):
    url = 'sqlite:///' + str(tmp_path / 'summary-migration.db')
    monkeypatch.setenv('NEXUS_DATABASE_URL', url)
    config = Config('alembic.ini')
    config.attributes['database_url'] = url
    command.upgrade(config, 'a8c4e2f1d7b3')
    engine = create_engine(url)
    session_id, tenant_id, run_id = '0' * 31 + '1', '0' * 31 + '2', '0' * 31 + '3'
    with engine.begin() as db:
        db.execute(text("INSERT INTO context_summaries (session_id, tenant_id, source_run_id, through_sequence, content) "
                         "VALUES (:s, :t, :r, 7, 'legacy')"), {'s': session_id, 't': tenant_id, 'r': run_id})
    command.upgrade(config, 'head')
    with engine.begin() as db:
        row = db.execute(text("SELECT id, session_id, supersedes_id, content FROM context_summaries")).one()
        assert row == (session_id, session_id, None, 'legacy')  # existing row becomes the first version
        db.execute(text("INSERT INTO context_summaries (id, session_id, tenant_id, source_run_id, through_sequence, content, supersedes_id, created_at) "
                        "VALUES ('" + '0' * 31 + "4', :s, :t, :r, 12, 'newer', :old, CURRENT_TIMESTAMP)"),
                   {'s': session_id, 't': tenant_id, 'r': run_id, 'old': session_id})
    command.downgrade(config, 'a8c4e2f1d7b3')
    with engine.connect() as db:
        rows = db.execute(text("SELECT session_id, through_sequence, content FROM context_summaries")).all()
        assert rows == [(session_id, 12, 'newer')]  # downgrade keeps only the effective summary
    command.upgrade(config, 'head')
    engine.dispose()
