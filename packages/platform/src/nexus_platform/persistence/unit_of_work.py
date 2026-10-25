"""Explicit transaction ownership for API sessions and worker-created sessions.

Borrowed sessions are never closed; worker sessions are always closed. A transaction
commits only on successful scope exit and rolls back on all exceptions. Existing
transactions are not silently nested: callers must preserve the application boundary.
"""
from __future__ import annotations

from sqlalchemy.orm import Session, sessionmaker


class SqlAlchemyUnitOfWork:
    """Own one transaction, optionally owning the session used by that transaction.

    source accepts a borrowed Session or a session factory. Reentry raises RuntimeError;
    SQLAlchemy's existing-transaction error is preserved rather than hidden by savepoints.
    """
    def __init__(self, source: Session | sessionmaker[Session]):
        self._source = source
        self._owns_session = not isinstance(source, Session)
        self._active = False
        self.session: Session

    def __enter__(self) -> SqlAlchemyUnitOfWork:
        if self._active:
            raise RuntimeError('Unit of work is already active')
        self.session = self._source() if self._owns_session else self._source
        transaction_started = False
        try:
            self._transaction = self.session.begin()
            self._transaction.__enter__()
            transaction_started = True
            connection = self.session.connection()
            if connection.dialect.name == "sqlite" and connection.dialect.driver == "pysqlite":
                # sqlite3 legacy mode does not BEGIN for SELECT or SAVEPOINT. A released
                # first savepoint would otherwise commit outside this outer transaction.
                # Honor engines that already emit BEGIN or use modern transaction control.
                driver = connection.connection.driver_connection
                if not driver.in_transaction:
                    connection.exec_driver_sql("BEGIN")
            self._bind_repositories()
        except BaseException:
            if transaction_started:
                self._transaction.rollback()
            if self._owns_session:
                self.session.close()
            raise
        self._active = True
        return self

    def _bind_repositories(self) -> None:
        """Bind all adapters to this transaction; never open an independent session."""
        # Instantiate transaction-bound adapters only after begin succeeded. They cannot
        # accidentally use a second session for authorization, event allocation or leasing.
        from nexus_platform.runs.repository import (
            SqlAlchemyRunRepository, SqlAlchemyRunEventRepository, SqlAlchemyOutboxRepository,
        )
        from nexus_platform.runs.submission_access import SqlAlchemySubmissionAccess
        from nexus_platform.runs.configuration_repository import SqlAlchemySubmissionCatalog
        from nexus_platform.runs.message_repository import SqlAlchemyRunMessageRepository
        from nexus_platform.runs.input_repository import SqlAlchemyRunInputRepository
        from nexus_platform.runs.audit_repository import SqlAlchemyRunAuditRepository
        self.runs = SqlAlchemyRunRepository(self.session)
        self.events = SqlAlchemyRunEventRepository(self.session)
        self.outbox = SqlAlchemyOutboxRepository(self.session)
        self.access = SqlAlchemySubmissionAccess(self.session)
        self.catalog = SqlAlchemySubmissionCatalog(self.session)
        self.messages = SqlAlchemyRunMessageRepository(self.session)
        self.inputs = SqlAlchemyRunInputRepository(self.session)
        self.audit = SqlAlchemyRunAuditRepository(self.session)

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return self._transaction.__exit__(exc_type, exc_value, traceback)
        finally:
            self._active = False
            if self._owns_session:
                self.session.close()
