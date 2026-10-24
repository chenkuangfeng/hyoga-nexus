from __future__ import annotations

import os
from collections.abc import Iterator

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker


def create_database_engine(url: str | None = None, *, echo: bool = False) -> Engine:
    database_url = url or os.environ.get("NEXUS_DATABASE_URL")
    if not database_url:
        raise RuntimeError("NEXUS_DATABASE_URL must be configured for platform operations")
    options: dict[str, object] = {"pool_pre_ping": True, "echo": echo}
    if database_url.startswith("sqlite"):
        options["connect_args"] = {"check_same_thread": False}
    return create_engine(database_url, **options)


def session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


def session_dependency(factory: sessionmaker[Session]) -> Iterator[Session]:
    session = factory()
    try:
        yield session
    finally:
        session.close()
