"""Session memory snapshots: frozen index per session, explicit refresh, owner-only access
(openspec 2026-11-01-memory-optimization, stage 2)."""
from uuid import uuid4

import pytest
from nexus_core.platform import Principal, TenantRole
from nexus_platform.errors import NotFound
from nexus_platform.identity.service import resolve_user
from nexus_platform.memory import snapshots
from nexus_platform.memory.repository import SqlMemoryRepository
from nexus_platform.persistence.models import SessionMemorySnapshotRecord
from nexus_platform.sessions.service import create_session
from nexus_platform.tenants.service import add_member

from test_native_runtime import stack
from test_platform import database  # noqa: F401 (pytest fixture)


def _publish(factory, run, title, text):
    with factory() as db:
        with db.begin():
            repo = SqlMemoryRepository(db)
            draft = repo.create_draft(tenant_id=run.tenant_id, source_run_id=run.id, kind='memory', diff=text,
                                      fingerprint=uuid4().hex + uuid4().hex, base_version=None, origin='foreground',
                                      source_message_ids=())
            entry = repo.create_entry(tenant_id=run.tenant_id, owner_id=run.principal_id, kind='memory',
                                      title=title, project='')
            repo.append_version(entry_id=entry.id, version=1, content=text, source_run_id=run.id,
                                source_draft_id=draft, reviewer_id=run.principal_id,
                                fingerprint=uuid4().hex + uuid4().hex, source_message_ids=())


def _index(factory, run, session_id):
    with factory() as db:
        with db.begin():
            return snapshots.session_index(db, tenant_id=run.tenant_id, owner_id=run.principal_id,
                                           session_id=session_id)


def test_later_runs_reuse_the_first_snapshot_even_after_memory_changes(database):  # noqa: F811
    _, tenant, session, run, _ = stack(database)
    _publish(database, run, 'Alpha Rule', 'alpha body')
    first = _index(database, run, session.id)
    assert 'Alpha Rule' in first
    _publish(database, run, 'Beta Rule', 'beta body')
    assert _index(database, run, session.id) == first
    with database() as db:
        assert db.get(SessionMemorySnapshotRecord, session.id).index_text == first


def test_explicit_refresh_makes_the_next_run_see_new_entries(database):  # noqa: F811
    principal, tenant, session, run, _ = stack(database)
    _publish(database, run, 'Alpha Rule', 'alpha body')
    _index(database, run, session.id)
    _publish(database, run, 'Beta Rule', 'beta body')
    with database() as db:
        snapshots.refresh_snapshot(db, principal, tenant.id, session.id)
    refreshed = _index(database, run, session.id)
    assert 'Alpha Rule' in refreshed and 'Beta Rule' in refreshed


def test_status_reports_staleness_and_refresh_clears_it(database):  # noqa: F811
    principal, tenant, session, run, _ = stack(database)
    with database() as db:
        assert snapshots.snapshot_status(db, principal, tenant.id, session.id) == {
            'exists': False, 'created_at': None, 'stale': False}
    _publish(database, run, 'Alpha Rule', 'alpha body')
    _index(database, run, session.id)
    with database() as db:
        status = snapshots.snapshot_status(db, principal, tenant.id, session.id)
    assert status['exists'] is True and status['stale'] is False
    _publish(database, run, 'Beta Rule', 'beta body')
    with database() as db:
        assert snapshots.snapshot_status(db, principal, tenant.id, session.id)['stale'] is True
    with database() as db:
        snapshots.refresh_snapshot(db, principal, tenant.id, session.id)
    with database() as db:
        assert snapshots.snapshot_status(db, principal, tenant.id, session.id)['exists'] is False


def test_snapshots_are_per_session(database):  # noqa: F811
    principal, tenant, session, run, _ = stack(database)
    _publish(database, run, 'Alpha Rule', 'alpha body')
    _index(database, run, session.id)
    _publish(database, run, 'Beta Rule', 'beta body')
    with database() as db:
        other = create_session(db, principal, tenant.id, agent_version_id=session.agent_version_id)
        other_id = other.id
    second = _index(database, run, other_id)
    assert 'Beta Rule' in second and 'Alpha Rule' in second


def test_only_the_session_owner_can_read_or_refresh_its_snapshot(database):  # noqa: F811
    principal, tenant, session, run, _ = stack(database)
    _index(database, run, session.id)
    member = Principal(id='snapshot-admin', issuer='test')
    with database() as db:
        add_member(db, principal, tenant.id, member, TenantRole.ADMIN)
    with database() as db:
        with pytest.raises(NotFound):
            snapshots.snapshot_status(db, member, tenant.id, session.id)
    with database() as db:
        with pytest.raises(NotFound):
            snapshots.refresh_snapshot(db, member, tenant.id, session.id)
    with database() as db:
        assert snapshots.snapshot_status(db, principal, tenant.id, session.id)['exists'] is True
