"""Skill tables migration: upgrade creates them, downgrade removes them, and the round trip is repeatable."""
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect


def _config(url):
    config = Config('alembic.ini')
    config.attributes['database_url'] = url
    return config


def test_skill_tables_round_trip_on_sqlite(tmp_path):
    url = 'sqlite:///' + str(tmp_path / 'skills.db')
    config = _config(url)
    command.upgrade(config, 'b8e2f1c4d7a9')
    engine = create_engine(url)
    assert 'skills' not in inspect(engine).get_table_names()
    command.upgrade(config, 'head')
    names = set(inspect(engine).get_table_names())
    assert {'skills', 'skill_versions', 'skill_version_files', 'session_skill_snapshots'} <= names
    command.downgrade(config, 'b8e2f1c4d7a9')
    assert 'skills' not in set(inspect(engine).get_table_names())
    command.upgrade(config, 'head')
    command.upgrade(config, 'head')
