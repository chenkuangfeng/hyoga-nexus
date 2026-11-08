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
    assert {'trust', 'scan_version', 'scan', 'extra', 'model_invocable', 'user_invocable', 'execution'} <= {
        c['name'] for c in inspector.get_columns('skill_versions')}
    with engine.begin() as connection:  # the widened constraint accepts the system kind
        connection.execute(text("INSERT INTO users (id, status, must_change_password, preferences, is_platform_admin,"
                                " created_at) VALUES ('u1', 'disabled', 0, '{}', 0, '2026-01-01')"))
        connection.execute(text("INSERT INTO tenants (id, name, kind, status, created_by, created_at, updated_at)"
                                " VALUES ('t1', 'System', 'system', 'active', 'u1', '2026-01-01', '2026-01-01')"))
    command.downgrade(config, PREVIOUS)
    inspector = inspect(engine)
    assert 'tenant_builtin_disabled' not in inspector.get_table_names()
    assert not {'trust', 'model_invocable', 'execution'} & {c['name'] for c in inspector.get_columns('skill_versions')}
    with engine.connect() as connection:  # downgrade removed the system space it could not keep
        assert connection.execute(text("SELECT count(*) FROM tenants WHERE kind = 'system'")).scalar() == 0
    command.upgrade(config, 'head')
    command.upgrade(config, 'head')


def test_skill_bundle_migration_adds_install_state_and_one_install_per_skill(tmp_path):
    url = 'sqlite:///' + str(tmp_path / 'bundle.db')
    config = _config(url)
    command.upgrade(config, 'd2e3f4a5b6c7')
    engine = create_engine(url)
    command.upgrade(config, 'head')
    inspector = inspect(engine)
    assert {'bundle', 'bundle_sha256', 'build_state', 'build_error', 'build_log', 'build_heartbeat_at',
            'env_ref'} <= {c['name'] for c in inspector.get_columns('skill_versions')}
    index = next(i for i in inspector.get_indexes('skill_versions') if i['name'] == 'uq_skill_versions_installing')
    assert index['unique'] and index['column_names'] == ['skill_id']
    command.downgrade(config, 'd2e3f4a5b6c7')
    assert 'build_state' not in {c['name'] for c in inspect(engine).get_columns('skill_versions')}
    command.upgrade(config, 'head')


def test_private_skill_migration_splits_name_uniqueness_and_adds_drafts(tmp_path):
    url = 'sqlite:///' + str(tmp_path / 'private.db')
    config = _config(url)
    command.upgrade(config, 'e3f4a5b6c7d8')
    engine = create_engine(url)
    command.upgrade(config, 'head')
    inspector = inspect(engine)
    assert {'owner_user_id', 'archived_at'} <= {c['name'] for c in inspector.get_columns('skills')}
    names = {i['name'] for i in inspector.get_indexes('skills')}
    assert {'uq_skills_library_name', 'uq_skills_private_name'} <= names
    assert 'skill_drafts' in inspector.get_table_names()
    command.downgrade(config, 'e3f4a5b6c7d8')
    inspector = inspect(engine)
    assert 'skill_drafts' not in inspector.get_table_names()
    assert 'owner_user_id' not in {c['name'] for c in inspector.get_columns('skills')}
    command.upgrade(config, 'head')


def test_skill_submission_migration_round_trip(tmp_path):
    url = 'sqlite:///' + str(tmp_path / 'submissions.db')
    config = _config(url)
    command.upgrade(config, 'f4a5b6c7d8e9')
    engine = create_engine(url)
    assert 'skill_submissions' not in inspect(engine).get_table_names()
    command.upgrade(config, 'head')
    assert 'skill_submissions' in inspect(engine).get_table_names()
    command.downgrade(config, 'f4a5b6c7d8e9')
    assert 'skill_submissions' not in inspect(engine).get_table_names()
    command.upgrade(config, 'head')


def test_skill_usage_migration_round_trip(tmp_path):
    url = 'sqlite:///' + str(tmp_path / 'usage.db')
    config = _config(url)
    command.upgrade(config, 'a5b6c7d8e9f0')
    engine = create_engine(url)
    command.upgrade(config, 'head')
    assert 'skill_usage' in inspect(engine).get_table_names()
    command.downgrade(config, 'a5b6c7d8e9f0')
    assert 'skill_usage' not in inspect(engine).get_table_names()
    command.upgrade(config, 'head')
