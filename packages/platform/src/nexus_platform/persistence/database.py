from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from nexus_platform.configuration import resolve_database_url


def create_database_engine(url: str | None = None, *, echo: bool = False) -> Engine:
    """Build an engine from an explicit URL or shared deployment configuration.

    Configuration errors are safe to display; no connection is opened until use.
    SQLite connection options remain available for isolated tests.
    """
    database_url = resolve_database_url(url)
    options: dict[str, object] = {"pool_pre_ping": True, "echo": echo}
    if database_url.startswith("sqlite"):
        options["connect_args"] = {"check_same_thread": False}
    return create_engine(database_url, **options)


def session_factory(engine: Engine) -> sessionmaker[Session]:
    # Releasing admissions on terminal Runs must apply to every session this factory creates.
    from nexus_platform.runs.session_ledger import install_run_terminal_hook
    install_run_terminal_hook()
    from nexus_platform.runs.bus.hook import install_run_event_hook
    install_run_event_hook()
    return sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


def session_dependency(factory: sessionmaker[Session]) -> Iterator[Session]:
    session = factory()
    try:
        yield session
    finally:
        session.close()
