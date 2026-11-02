"""Typed models migration: existing defaults become chat defaults and the change can be reversed."""
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text


def test_model_type_migration_keeps_defaults_as_chat_and_downgrades(tmp_path):
    url = 'sqlite:///' + str(tmp_path / 'model-types.db')
    config = Config('alembic.ini')
    config.attributes["database_url"] = url
    command.upgrade(config, 'e6d1a7b3c8f2')
    engine = create_engine(url)
    with engine.begin() as db:
        db.execute(text("INSERT INTO model_defaults (tenant_id, scope_key, version_id) VALUES ('t1', 'tenant', 'v1')"))
        db.execute(text("INSERT INTO model_defaults (tenant_id, scope_key, version_id) VALUES ('t1', 'u1', 'v2')"))
    command.upgrade(config, 'head')
    command.upgrade(config, 'head')
    with engine.begin() as db:
        rows = db.execute(text("SELECT tenant_id, scope_key, model_type, version_id FROM model_defaults ORDER BY scope_key")).all()
        assert [tuple(row) for row in rows] == [('t1', 'tenant', 'chat', 'v1'), ('t1', 'u1', 'chat', 'v2')]
        columns = {row[1] for row in db.execute(text('PRAGMA table_info(model_profiles)'))}
        assert 'model_type' in columns
        # The primary key now includes the type, so one scope can hold one default per type.
        db.execute(text("INSERT INTO model_defaults (tenant_id, scope_key, model_type, version_id) VALUES ('t1', 'tenant', 'embedding', 'v3')"))
    command.downgrade(config, 'e6d1a7b3c8f2')
    with engine.begin() as db:
        rows = db.execute(text("SELECT tenant_id, scope_key, version_id FROM model_defaults ORDER BY scope_key")).all()
        assert [tuple(row) for row in rows] == [('t1', 'tenant', 'v1'), ('t1', 'u1', 'v2')]
        assert 'model_type' not in {row[1] for row in db.execute(text('PRAGMA table_info(model_profiles)'))}
    command.upgrade(config, 'head')
    engine.dispose()
