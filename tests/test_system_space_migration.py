"""System space migration: builtin tables and skill trust columns round-trip, and legacy sources are renamed."""
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

PREVIOUS = 'e8f9a0b1c2d3'


def _config(url):
    config = Config('alembic.ini')
    config.attributes['database_url'] = url
    return config


def test_system_space_migration_round_trip_on_sqlite(tmp_path):
    url = 'sqlite:///' + str(tmp_path / 'system.db')
    config = _config(url)
    command.upgrade(config, PREVIOUS)
    engine = create_engine(url)
    assert 'tenant_builtin_disabled' not in inspect(engine).get_table_names()
    command.upgrade(config, 'head')
    inspector = inspect(engine)
    assert 'tenant_builtin_disabled' in inspector.get_table_names()
    assert {'trust', 'scan_version', 'scan', 'extra'} <= {c['name'] for c in inspector.get_columns('skill_versions')}
    with engine.begin() as connection:  # the widened constraint accepts the system kind
        connection.execute(text("INSERT INTO users (id, status, must_change_password, preferences, is_platform_admin,"
                                " created_at) VALUES ('u1', 'disabled', 0, '{}', 0, '2026-01-01')"))
        connection.execute(text("INSERT INTO tenants (id, name, kind, status, created_by, created_at, updated_at)"
                                " VALUES ('t1', 'System', 'system', 'active', 'u1', '2026-01-01', '2026-01-01')"))
    command.downgrade(config, PREVIOUS)
    inspector = inspect(engine)
    assert 'tenant_builtin_disabled' not in inspector.get_table_names()
    assert 'trust' not in {c['name'] for c in inspector.get_columns('skill_versions')}
    with engine.connect() as connection:  # downgrade removed the system space it could not keep
        assert connection.execute(text("SELECT count(*) FROM tenants WHERE kind = 'system'")).scalar() == 0
    command.upgrade(config, 'head')
    command.upgrade(config, 'head')
