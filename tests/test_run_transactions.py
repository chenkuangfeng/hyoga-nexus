"""Persistence failure probes for the Run transaction boundary and legacy adapters."""
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.exc import InvalidRequestError
from sqlalchemy.orm import Session, sessionmaker

from nexus_core.platform import Principal, new_id, utc_now
from nexus_platform.persistence.base import Base
from nexus_platform.persistence.models import (
    AuditRecord, MessageRecord, OutboxRecord, RunEventRecord, RunRecord, UserRecord,
)
from nexus_platform.persistence.unit_of_work import SqlAlchemyUnitOfWork
from nexus_platform.runs.service import create_run, claim_next
from test_platform import create_agent_stack, database


def test_submission_failure_rolls_back_snapshot_message_event_audit_and_queue(database):
    principal = Principal(id="atomic", issuer="test")
    tenant, _, _, _, _, session = create_agent_stack(database, principal)
    tables = (RunRecord, MessageRecord, RunEventRecord, AuditRecord, OutboxRecord)
    with database() as db:
        baseline = [db.scalar(select(func.count()).select_from(table)) for table in tables]
    # Fail after all Run-side writes, including the event flush, before transaction exit.
    with database() as db, patch(
        "nexus_platform.runs.audit_repository.audit", side_effect=RuntimeError("audit unavailable")
    ):
        with pytest.raises(RuntimeError, match="audit unavailable"):
            create_run(db, principal, tenant.id, session.id,
                       message="hello", idempotency_key="retry-after-rollback")
        assert not db.in_transaction()
    with database() as db:
        assert [db.scalar(select(func.count()).select_from(table)) for table in tables] == baseline
    with database() as db:
        # The failed key remains reusable; the failed transaction did not leave a Run.
        run, replay = create_run(db, principal, tenant.id, session.id,
                                 message="hello", idempotency_key="retry-after-rollback")
        assert not replay
    with database() as db:
        assert db.scalar(select(RunEventRecord.run_id)) == run.id
        assert db.scalar(select(OutboxRecord.run_id)) == run.id


def test_claim_rollback_does_not_consume_lease_or_attempt(database):
    principal = Principal(id="lease-atomic", issuer="test")
    tenant, _, _, _, _, session = create_agent_stack(database, principal)
    with database() as db:
        create_run(db, principal, tenant.id, session.id, message="hello", idempotency_key="lease")
    with database() as db:
        with pytest.raises(RuntimeError, match="worker died"):
            with SqlAlchemyUnitOfWork(db) as work:
                now = utc_now()
                assert work.outbox.claim("failed-worker", now, now) is not None
                # Exercise an actual database flush before rollback.
                db.flush()
                raise RuntimeError("worker died")
    with database() as db:
        task = db.scalar(select(OutboxRecord))
        assert (task.attempts, task.lease_owner, task.lease_until) == (0, None, None)
    with database() as db:
        assert claim_next(db, "replacement-worker") == task.id
    with database() as db:
        task = db.get(OutboxRecord, task.id)
        assert (task.attempts, task.lease_owner) == (1, "replacement-worker")


def test_unit_of_work_ownership_reentry_and_failed_begin():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    closed = []

    class TrackedSession(Session):
        def close(self):
            closed.append(self)
            super().close()

    factory = sessionmaker(bind=engine, class_=TrackedSession, expire_on_commit=False)
    user_id = new_id()
    try:
        with factory() as borrowed:
            work = SqlAlchemyUnitOfWork(borrowed)
            with work:
                borrowed.add(UserRecord(id=user_id, display_name="uow",
                                        status="active", created_at=utc_now()))
                with pytest.raises(RuntimeError, match="already active"):
                    work.__enter__()
            assert borrowed not in closed
            with borrowed.begin():
                with pytest.raises(InvalidRequestError):
                    SqlAlchemyUnitOfWork(borrowed).__enter__()
                assert borrowed.get(UserRecord, user_id) is not None
        with SqlAlchemyUnitOfWork(factory) as owned:
            assert owned.session.get(UserRecord, user_id) is not None
        assert owned.session in closed
        with pytest.raises(RuntimeError, match="rollback"):
            with SqlAlchemyUnitOfWork(factory) as failed:
                failed.session.add(UserRecord(id=new_id(), display_name="rolled-back",
                                              status="active", created_at=utc_now()))
                failed.session.flush()
                raise RuntimeError("rollback")
        assert failed.session in closed
        with factory() as db:
            assert list(db.scalars(select(UserRecord.display_name))) == ["uow"]
    finally:
        engine.dispose()


def test_split_modules_preserve_public_type_identity_and_metadata():
    from nexus_core.runtime import ModelMessage, ToolCall
    from nexus_core.runtime.models import ModelMessage as Message
    from nexus_core.runtime.tools import ToolCall as Call
    from nexus_core.native import NativePolicy
    from nexus_core.native.policy import NativePolicy as Policy
    from nexus_platform.persistence.models.identity import UserRecord as User
    assert (ModelMessage, ToolCall, NativePolicy, UserRecord) == (Message, Call, Policy, User)
    assert all(mapper.local_table.metadata is Base.metadata for mapper in Base.registry.mappers)
    assert len(Base.metadata.tables) == 69  # includes action_grants, memory_topic_stats, memory_embeddings, memory_consolidation_state, memory_space_settings, the four skill tables (skills, skill_versions, skill_version_files, session_skill_snapshots), agent_shares, space_invite_links, tool_outputs (P2), org_units and user_org_units, the space tables (space_join_requests, shared_spaces, shared_space_*), memory_tombstones, session_memory_snapshots and the three memory_capture tables
    # Resolve every cross-module string foreign key, rather than just count the tables.
    assert all(foreign_key.column is not None for table in Base.metadata.tables.values()
               for foreign_key in table.foreign_keys)
