from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text


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
    engine.dispose()

    command.downgrade(config, "base")
    command.upgrade(config, "head")
