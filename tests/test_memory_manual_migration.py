"""Manual memories preserve legacy provenance while permitting truthful Run-free sources."""
from alembic import command
from sqlalchemy import create_engine, inspect

from test_memory_stage1_migration import _config


def test_manual_source_migration_can_upgrade_and_repeat(tmp_path):
    url = 'sqlite:///' + str(tmp_path / 'manual-memory.db')
    config = _config(url)
    command.upgrade(config, 'c6a1e9d4b730')
    engine = create_engine(url)
    for table in ('memory_drafts', 'memory_versions'):
        assert not next(c for c in inspect(engine).get_columns(table) if c['name'] == 'source_run_id')['nullable']
    command.upgrade(config, 'b7c8d9e0f1a2')
    command.upgrade(config, 'b7c8d9e0f1a2')
    for table in ('memory_drafts', 'memory_versions'):
        assert next(c for c in inspect(engine).get_columns(table) if c['name'] == 'source_run_id')['nullable']
    command.downgrade(config, 'c6a1e9d4b730')
    command.upgrade(config, 'b7c8d9e0f1a2')
