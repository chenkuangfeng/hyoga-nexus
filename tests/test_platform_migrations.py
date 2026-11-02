from alembic import command
from alembic.config import Config
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, text
from nexus_platform.persistence.models import Base


def _is_keyword_index(item):
    """FTS5 virtual tables and their shadow tables (memory_fts*) are created by the migration and by
    the metadata DDL event on SQLite; they are not ORM mappings, so schema comparison ignores them."""
    parts = item if isinstance(item, (list, tuple)) else [item]
    return any(str(getattr(part, 'name', part)).startswith('memory_fts') for part in parts)


def _unmapped_differences(connection):
    differences = []
    for op in compare_metadata(MigrationContext.configure(connection), Base.metadata):
        if isinstance(op, list):
            kept = [inner for inner in op if not _is_keyword_index(inner)]
            if kept:
                differences.append(kept)
        elif not _is_keyword_index(op):
            differences.append(op)
    return differences


def test_platform_migration_upgrade_downgrade_roundtrip(tmp_path):
    url = "sqlite:///" + str(tmp_path / "platform.db")
    config = Config("alembic.ini")
    config.attributes["database_url"] = url

    command.upgrade(config, "head")
    engine = create_engine(url)
    with engine.connect() as connection:
        tables = {
            row[0]
            for row in connection.execute(
                text("SELECT name FROM sqlite_master WHERE type='table'")
            )
        }
        assert {"users", "tenant_memberships", "agent_versions", "runs", "run_events", "outbox_records"} <= tables
        assert _unmapped_differences(connection) == []
    engine.dispose()

    command.downgrade(config, "base")
    command.upgrade(config, "head")
