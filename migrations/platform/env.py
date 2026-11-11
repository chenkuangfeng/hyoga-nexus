from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from nexus_platform.persistence.models import Base
from nexus_platform.configuration import resolve_database_url

config = context.config
if config.config_file_name is not None:
    # Keep the loggers that already exist: the default (True) silences every one of them, which hides the worker's and
    # the API's logs whenever a migration runs in the same process (tests, embedded start-up).
    fileConfig(config.config_file_name, disable_existing_loggers=False)

database_url = resolve_database_url(config.attributes.get("database_url"))
config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
