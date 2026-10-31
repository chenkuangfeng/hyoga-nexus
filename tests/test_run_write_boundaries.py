"""Real-database contract and failure tests for Run application/repository separation."""
from dataclasses import replace
import subprocess
import sys
from unittest.mock import patch

import pytest
from sqlalchemy import func, inspect, select
from sqlalchemy.exc import IntegrityError

from nexus_core.platform import Principal, TenantRole, new_id, utc_now
from nexus_platform.errors import Conflict, Forbidden, NotFound
from nexus_platform.persistence.models import (
    AuditRecord, InputRequestRecord, MessageRecord, OutboxRecord, RunEventRecord, RunRecord, UserRecord,
)
from nexus_platform.persistence.unit_of_work import SqlAlchemyUnitOfWork
from nexus_platform.runs.domain import Run
from nexus_platform.runs.execution import respond_input
from nexus_platform.runs.service import create_run, list_events, request_cancel
from nexus_platform.tenants.service import add_member, create_tenant
from test_platform import create_agent_stack, database


def test_application_services_import_without_loading_sqlalchemy():
    """Prevent future facade imports from silently reintroducing ORM into application modules."""
    subprocess.run([sys.executable, '-c', """
import sys
from nexus_platform.runs.submission import RunSubmissionService
from nexus_platform.runs.cancellation import RunCancellationService
from nexus_platform.runs.inputs import RunInputService
from nexus_platform.runs.leasing import RunLeaseService
assert 'sqlalchemy' not in sys.modules
"""], check=True)


def submitted(factory):
    principal = Principal(id='write-boundary', issuer='test')
    tenant, _, _, _, _, session = create_agent_stack(factory, principal)
    with factory() as db:
        run, _ = create_run(db, principal, tenant.id, session.id,
                            message='initial', idempotency_key='initial')
    return principal, tenant, session, run


def waiting(factory):
    principal, tenant, session, run = submitted(factory)
    with factory() as db, db.begin():
        db.get(RunRecord, run.id).status = 'waiting_input'
        task = db.scalar(select(OutboxRecord).where(OutboxRecord.run_id == run.id))
        task.completed_at = utc_now()
        request = InputRequestRecord(id=new_id(), run_id=run.id, question='Which?',
                                     candidates=['A', 'B'], created_at=utc_now())
        db.add(request)
    return principal, tenant, session, run, request


def test_domain_values_are_independent_and_require_explicit_save(database):
    _, tenant, _, run = submitted(database)
    original = run.config_snapshot
    with SqlAlchemyUnitOfWork(database) as work:
        value = work.runs.owned_for_update(tenant.id, run.principal_id, run.id)
        assert type(value) is Run
        assert inspect(value, raiseerr=False) is None
        value.error_message = 'unsaved'
        value.config_snapshot['budgets']['max_rounds'] = 99
    with database() as db:
        stored = db.get(RunRecord, run.id)
        assert stored.error_message is None
        assert stored.config_snapshot == original
    with SqlAlchemyUnitOfWork(database) as work:
        value = work.runs.owned_for_update(tenant.id, run.principal_id, run.id)
        value.error_message = 'explicitly saved'
        value.config_snapshot['budgets']['max_rounds'] = 8
        work.runs.save(value)
    with database() as db:
        stored = db.get(RunRecord, run.id)
        assert stored.error_message == 'explicitly saved'
        assert stored.config_snapshot['budgets']['max_rounds'] == 8


def test_savepoint_collision_replays_scoped_key_and_preserves_outer_transaction(database):
    _, tenant, _, run = submitted(database)
    # Only executing Runs are unique per session; queued Runs may wait behind one another.
    with database() as db:
        db.get(RunRecord, run.id).status = 'running'
        db.commit()
    with SqlAlchemyUnitOfWork(database) as work:
        value = work.runs.owned_for_update(tenant.id, run.principal_id, run.id)
        collided, inserted = work.runs.insert_or_replay(replace(value, id=new_id()))
        assert not inserted
        assert collided.id == run.id
        assert collided.request_hash == run.request_hash
        # An unrelated active-Session uniqueness failure must remain an integrity error.
        with pytest.raises(IntegrityError):
            work.runs.insert_or_replay(replace(value, id=new_id(), idempotency_key='different'))
        assert work.runs.by_key(tenant.id, run.principal_id, 'different') is None
        work.events.append(run.id, 'test.outer-still-active', {}, utc_now())
    with database() as db:
        assert db.scalar(select(func.count()).select_from(RunRecord)) == 1
        assert list(db.scalars(select(RunEventRecord.sequence).order_by(RunEventRecord.sequence))) == [1, 2]


def test_legacy_results_reuse_mapped_identity_without_post_commit_transaction(database):
    principal, tenant, session, run = submitted(database)
    with database() as db:
        replayed, replay = create_run(db, principal, tenant.id, session.id,
                                     message='initial', idempotency_key='initial')
        assert replay
        assert not db.in_transaction()
        assert inspect(replayed).session is db
        cancelled = request_cancel(db, principal, tenant.id, run.id)
        assert cancelled is replayed
        assert not db.in_transaction()
        assert cancelled.status == 'cancelled'
    principal, tenant, _, run, request = waiting_new_session(database, principal, tenant, session)
    with database() as db:
        responded = respond_input(db, principal, tenant.id, run.id, request.id, 'A', 'answer')
        assert inspect(responded).session is db
        assert not db.in_transaction()


def waiting_new_session(factory, principal, tenant, previous_session):
    """Use a separate fixed-version Session after an earlier Run has completed."""
    from nexus_platform.sessions.service import create_session
    with factory() as db:
        session = create_session(db, principal, tenant.id,
                                 agent_version_id=previous_session.agent_version_id, title='second')
    with factory() as db:
        run, _ = create_run(db, principal, tenant.id, session.id,
                            message='resume', idempotency_key='second')
    with factory() as db, db.begin():
        db.get(RunRecord, run.id).status = 'waiting_input'
        db.scalar(select(OutboxRecord).where(OutboxRecord.run_id == run.id)).completed_at = utc_now()
        request = InputRequestRecord(id=new_id(), run_id=run.id, question='Which?',
                                     candidates=[], created_at=utc_now())
        db.add(request)
    return principal, tenant, session, run, request


@pytest.mark.parametrize('status', ['queued', 'waiting_input', 'waiting_approval'])
def test_idle_cancel_event_order_and_terminal_noop(database, status):
    principal, tenant, _, run = submitted(database)
    with database() as db, db.begin():
        db.get(RunRecord, run.id).status = status
    with database() as db:
        cancelled = request_cancel(db, principal, tenant.id, run.id)
        assert cancelled.status == 'cancelled'
    with database() as db:
        request_cancel(db, principal, tenant.id, run.id)
        events = list_events(db, principal, tenant.id, run.id, 0)
        assert [event.event_type for event in events] == [
            'run.queued', 'run.cancelled', 'run.cancel_requested',
        ]
    with database() as db:
        assert db.scalar(select(OutboxRecord.completed_at)) is not None
        assert db.get(RunRecord, run.id).ended_at is not None


def test_active_cancel_preserves_status_and_single_delivery(database):
    principal, tenant, _, run = submitted(database)
    with database() as db, db.begin():
        db.get(RunRecord, run.id).status = 'running'
    with database() as db:
        assert request_cancel(db, principal, tenant.id, run.id).status == 'running'
        assert request_cancel(db, principal, tenant.id, run.id).status == 'running'
    with database() as db:
        deliveries = list(db.scalars(select(OutboxRecord).where(OutboxRecord.message_type == 'run.cancel')))
        assert len(deliveries) == 1
        stored = db.get(RunRecord, run.id)
        assert stored.ended_at is None
        assert stored.cancel_requested_at is not None


@pytest.mark.parametrize('operation', ['cancel', 'respond'])
def test_member_and_cross_tenant_cannot_mutate_another_run(database, operation):
    principal, tenant, _, run, request = waiting(database)
    bob = Principal(id='other-member', issuer='test')
    with database() as db:
        add_member(db, principal, tenant.id, bob, TenantRole.MEMBER)
        other_tenant = create_tenant(db, principal, 'other')
    for actor, space in [(bob, tenant.id), (principal, other_tenant.id)]:
        with database() as db, pytest.raises(NotFound):
            if operation == 'cancel':
                request_cancel(db, actor, space, run.id)
            else:
                respond_input(db, actor, space, run.id, request.id, 'A', 'attempt')
    with database() as db:
        assert db.get(RunRecord, run.id).status == 'waiting_input'
        assert db.get(InputRequestRecord, request.id).responded_at is None
        assert db.scalar(select(func.count()).select_from(RunEventRecord)) == 1


@pytest.mark.parametrize('operation', ['cancel', 'respond'])
def test_failed_audit_rolls_back_cancellation_or_input_and_queue(database, operation):
    principal, tenant, session, run, request = waiting(database)
    with database() as db:
        baseline_audit = db.scalar(select(func.count()).select_from(AuditRecord))
    with database() as db, patch('nexus_platform.runs.audit_repository.audit',
                                 side_effect=RuntimeError('audit offline')):
        with pytest.raises(RuntimeError, match='audit offline'):
            if operation == 'cancel':
                request_cancel(db, principal, tenant.id, run.id)
            else:
                respond_input(db, principal, tenant.id, run.id, request.id, 'A', 'answer')
        assert not db.in_transaction()
    with database() as db:
        stored = db.get(RunRecord, run.id)
        assert stored.status == 'waiting_input'
        assert stored.cancel_requested_at is None
        assert stored.ended_at is None
        assert db.get(InputRequestRecord, request.id).responded_at is None
        assert db.scalar(select(OutboxRecord.completed_at)) is not None
        assert db.scalar(select(func.count()).select_from(MessageRecord)) == 1
        assert db.scalar(select(func.count()).select_from(RunEventRecord)) == 1
        assert db.scalar(select(func.count()).select_from(AuditRecord)) == baseline_audit
    # A failed response leaves both the input and key available for the actual retry.
    if operation == 'respond':
        with database() as db:
            respond_input(db, principal, tenant.id, run.id, request.id, 'A', 'answer')
        with database() as db:
            assert db.get(InputRequestRecord, request.id).response_key == 'answer'
            assert db.scalar(select(OutboxRecord.completed_at)) is None


def test_input_key_is_preserved_and_consumed_replay_precedes_run_state_check(database):
    principal, tenant, _, run, request = waiting(database)
    with database() as db:
        respond_input(db, principal, tenant.id, run.id, request.id, 'A', ' answer ')
    with database() as db:
        request_cancel(db, principal, tenant.id, run.id)
        replayed = respond_input(db, principal, tenant.id, run.id, request.id, 'A', ' answer ')
        assert replayed.status == 'cancelled'
        with pytest.raises(Conflict, match='already consumed'):
            respond_input(db, principal, tenant.id, run.id, request.id, 'A', 'answer')
        with pytest.raises(Conflict, match='already consumed'):
            respond_input(db, principal, tenant.id, run.id, request.id, 'B', ' answer ')
    with database() as db:
        assert db.scalar(select(func.count()).select_from(MessageRecord)) == 2
        assert db.get(InputRequestRecord, request.id).response_key == ' answer '


def test_disabled_principal_cannot_use_idempotent_submission_replay(database):
    principal, tenant, session, run = submitted(database)
    with database() as db, db.begin():
        db.get(UserRecord, run.principal_id).status = 'disabled'
    with database() as db, pytest.raises(Forbidden, match='disabled'):
        create_run(db, principal, tenant.id, session.id,
                   message='initial', idempotency_key='initial')
    with database() as db:
        assert db.scalar(select(func.count()).select_from(RunRecord)) == 1
        assert db.scalar(select(func.count()).select_from(MessageRecord)) == 1
