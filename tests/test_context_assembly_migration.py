"""Provenance migration retains populated pre-change data and is safe to reapply."""
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from nexus_platform.persistence.models import SessionMemorySnapshotRecord, RunRecord
from nexus_core.platform import utc_now
from test_native_runtime import stack


def test_context_migration_populated_upgrade_and_repeat(tmp_path):
    url = 'sqlite:///' + str(tmp_path / 'context.db')
    config = Config('alembic.ini')
    config.attributes['database_url'] = url
    command.upgrade(config, 'head')
    engine = create_engine(url)
    factory = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    _, _, session, run, _ = stack(factory)
    with factory() as db, db.begin():
        db.get(RunRecord, run.id).status = 'completed'
        db.add(SessionMemorySnapshotRecord(session_id=session.id, tenant_id=run.tenant_id,
            owner_user_id=run.principal_id, index_text='legacy', version_key='a' * 64,
            created_at=utc_now(), context_dependencies=[]))
    engine.dispose()
    command.downgrade(config, 'f2c4a6b8d0e1')
    command.upgrade(config, 'head')
    command.upgrade(config, 'head')
    with engine.connect() as db:
        assert db.execute(text('select index_text from session_memory_snapshots')).scalar_one() == 'legacy'
        assert db.execute(text('select context_dependencies from session_memory_snapshots')).scalar_one() is None
        assert db.execute(text('select count(*) from runs')).scalar_one() == 1
        assert 'run_context_blocks' in inspect(db).get_table_names()
        assert '"schema_version": 0' in db.execute(text('select context_manifest from runs')).scalar_one()
    engine.dispose()
