from alembic import command
from alembic.config import Config
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, text
from nexus_platform.persistence.models import Base


def test_platform_migration_upgrade_downgrade_roundtrip(tmp_path, monkeypatch):
    url = "sqlite:///" + str(tmp_path / "platform.db")
    monkeypatch.setenv("NEXUS_DATABASE_URL", url)
    config = Config("alembic.ini")

    command.upgrade(config, "head")
    engine = create_engine(url)
    with engine.connect() as connection:
        tables = {
            row[0]
            for row in connection.execute(
                text("SELECT name FROM sqlite_master WHERE type='table'")
            )
        }
        assert {"users", "workspace_memberships", "agent_versions", "runs", "run_events", "outbox_records"} <= tables
        assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []
    engine.dispose()

    command.downgrade(config, "base")
    command.upgrade(config, "head")
