from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from nexus_platform.configuration import resolve_database_url


def create_database_engine(url: str | None = None, *, echo: bool = False, pool_size: int | None = None) -> Engine:
    """Build an engine from an explicit URL or shared deployment configuration.

    Configuration errors are safe to display; no connection is opened until use.
    SQLite connection options remain available for isolated tests. ``pool_size`` sets how many connections the
    pool keeps (and, with no overflow, the most it opens); None keeps SQLAlchemy's defaults. It is ignored for
    in-memory SQLite, which uses a single shared connection.
    """
    database_url = resolve_database_url(url)
    options: dict[str, object] = {"pool_pre_ping": True, "echo": echo}
    if database_url.startswith("sqlite"):
        options["connect_args"] = {"check_same_thread": False}
    in_memory = database_url in ("sqlite://", "sqlite:///:memory:") or ":memory:" in database_url
    if pool_size is not None and not in_memory:
        options["pool_size"], options["max_overflow"] = pool_size, 0
    engine = create_engine(database_url, **options)
    if database_url.startswith("sqlite") and not in_memory:
        configure_sqlite_concurrency(engine)
    return engine


#: Seconds a SQLite writer waits for the lock before giving up.
SQLITE_BUSY_TIMEOUT_SECONDS = 30


def configure_sqlite_concurrency(engine: Engine) -> None:
    """Let several threads write to one SQLite file: writers queue instead of failing.

    SQLite allows one writer. Its default deferred transaction starts as a reader and fails at once with
    "database is locked" when it tries to become a writer while another writer commits. Starting every
    transaction with ``BEGIN IMMEDIATE`` takes the write lock up front, where the busy timeout makes a
    contender wait; WAL lets readers proceed during a write. This is the recipe from SQLAlchemy's SQLite notes.
    """
    @event.listens_for(engine, "connect")
    def _connect(dbapi_connection, _record):
        dbapi_connection.isolation_level = None  # the driver must not start transactions on its own
        dbapi_connection.execute(f"PRAGMA busy_timeout = {SQLITE_BUSY_TIMEOUT_SECONDS * 1000}")
        dbapi_connection.execute("PRAGMA journal_mode = WAL")

    @event.listens_for(engine, "begin")
    def _begin(connection):
        connection.exec_driver_sql("BEGIN IMMEDIATE")


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
