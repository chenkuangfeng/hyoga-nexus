"""Retention of sessions and hash-chained audit export (openspec 2026-11-11-enterprise-saas E7)."""
import json
from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

from nexus_api.dependencies.platform import get_database_session, get_principal
from nexus_api.main import app
from nexus_core.platform import Principal, new_id, utc_now
from nexus_platform.governance import retention
from nexus_platform.persistence.models import (ArtifactRecord, MessageRecord, RunEventRecord, RunRecord,
                                               SessionRecord)
from nexus_platform.runs.compatibility import create_run
from nexus_platform.tenants.policies import update_policy

from test_platform import create_agent_stack, database  # noqa: F401 (pytest fixture)

OWNER = Principal('gov-owner', 'test')


def test_retention_purges_old_idle_sessions_only(database, tmp_path):
    tenant, _, _, _, _, session = create_agent_stack(database, OWNER)
    with database() as db:
        run, _ = create_run(db, OWNER, tenant.id, session.id, message='old question', idempotency_key='r1')
    stored = tmp_path / 'a' / 'file.txt'
    stored.parent.mkdir()
    stored.write_text('secret')
    with database() as db, db.begin():
        db.get(RunRecord, run.id).status = 'completed'
        db.add(ArtifactRecord(id=new_id(), tenant_id=tenant.id, session_id=session.id, run_id=run.id,
                              owner_user_id=db.get(SessionRecord, session.id).owner_user_id, path='file.txt',
                              name='file.txt', storage_key='a/file.txt', size=6, sha256='0' * 64,
                              mime='text/plain', created_at=utc_now()))
        db.get(SessionRecord, session.id).updated_at = utc_now() - timedelta(days=40)
    with database() as db:
        assert retention.run_retention(db, root=tmp_path) == {}  # no retention period set
    with database() as db:
        update_policy(db, OWNER, tenant.id, {'retention_days': 30})
    with database() as db:
        assert retention.run_retention(db, root=tmp_path) == {str(tenant.id): 1}
    with database() as db:
        assert db.get(SessionRecord, session.id).status == 'purged'
        assert db.scalars(select(MessageRecord).where(MessageRecord.session_id == session.id)).all() == []
        assert db.scalars(select(RunEventRecord).where(RunEventRecord.run_id == run.id)).all() == []
        assert db.get(RunRecord, run.id) is not None  # the Run row stays for usage and audit
    assert not stored.exists()


def test_busy_or_recent_sessions_are_kept(database, tmp_path):
    tenant, _, _, _, _, session = create_agent_stack(database, OWNER)
    with database() as db:
        create_run(db, OWNER, tenant.id, session.id, message='still queued', idempotency_key='q1')
    with database() as db, db.begin():
        db.get(SessionRecord, session.id).updated_at = utc_now() - timedelta(days=40)
    with database() as db:
        update_policy(db, OWNER, tenant.id, {'retention_days': 30})
    with database() as db:
        assert retention.run_retention(db, root=tmp_path) == {}


def test_audit_export_is_hash_chained_and_audited(database):
    tenant, *_ = create_agent_stack(database, OWNER)
    app.state.session_factory = database

    def override_db():
        with database() as db:
            yield db

    app.dependency_overrides[get_database_session] = override_db
    app.dependency_overrides[get_principal] = lambda: OWNER
    try:
        with TestClient(app) as client:
            exported = client.get(f'/api/v1/tenants/{tenant.id}/admin/audit/export')
            assert exported.status_code == 200 and exported.headers['content-type'].startswith('application/x-ndjson')
            lines = exported.text.splitlines()
    finally:
        app.dependency_overrides.clear()
        app.state.session_factory = None
    assert lines and retention.verify_lines(tenant.id, lines)
    assert any(json.loads(line)['action'] == 'audit.exported' for line in lines)
    tampered = [lines[0].replace('"action": "', '"action": "x')] + lines[1:]
    assert not retention.verify_lines(tenant.id, tampered)
    assert not retention.verify_lines(tenant.id, lines[1:])  # a removed line breaks the chain
