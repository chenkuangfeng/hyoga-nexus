"""Memory capture with the owner's own model key (openspec 2026-11-01-memory-optimization, stage 3.5).

The key is the one the owner stored for the capture model. It is resolved per call, used in memory,
audited with purpose `memory.capture`, and never written to the job, drafts or errors.
"""
from datetime import timedelta
from uuid import UUID

from cryptography.fernet import Fernet

from nexus_core.platform import utc_now
from nexus_platform.memory import capture
from nexus_platform.models.provider_settings import save_model, save_provider
from nexus_platform.persistence.models import AuditRecord, MemoryCaptureJobRecord
from nexus_worker import memory_capture as worker_capture
from nexus_worker.memory_capture import capture_tick, owner_extractor

from test_memory_capture import _drafts, _enqueue, _messages
from test_memory_capture_extractor import ScriptedModel
from test_native_runtime import stack
from test_platform import database  # noqa: F401 (pytest fixture)

SECRET = 'owner-secret-key-123'


def _owner_model(database, principal, tenant_id, deployment_config, protocol='openai_chat_completions'):
    """A capture model that uses the owner's personal key, stored encrypted like any provider key."""
    deployment_config(f'[security]\ncredential_encryption_key = "{Fernet.generate_key().decode()}"\n')
    with database() as db:
        provider = save_provider(db, principal, tenant_id, name='Mine', base_url='https://model.example/v1',
                                 scope='personal', api_key=SECRET)
    with database() as db:
        model = save_model(db, principal, tenant_id, UUID(str(provider['id'])), 'capture-model',
                           model_options={'protocol': protocol})
    return UUID(str(model['version_id']))


def _enable(database, principal, tenant_id, version_id):
    with database() as db:
        capture.set_capture(db, principal, tenant_id, enabled=True, model_profile_version_id=version_id,
                            capacity_policy='reject')


def test_owner_key_is_used_per_call_and_each_use_is_audited(database, monkeypatch, deployment_config):  # noqa: F811
    principal, tenant, session, run, _ = stack(database)
    version_id = _owner_model(database, principal, tenant.id, deployment_config)
    _enable(database, principal, tenant.id, version_id)
    _messages(database, session.id, 4)
    job_id = UUID(_enqueue(database, run.id, utc_now()))
    fake = ScriptedModel('[{"op":"add","kind":"memory","diff":"Owner fact"}]')
    seen = {}

    def fake_create_model(**kwargs):
        seen.update(kwargs)
        return fake
    monkeypatch.setattr(worker_capture, 'create_model', fake_create_model)

    state = capture.run_due(database, owner_extractor(database), worker_id='w1', now=utc_now() + timedelta(hours=1))
    assert state == 'completed'
    assert seen['api_key'] == SECRET and seen['model'] == 'capture-model'
    assert _drafts(database, run) == [('capture', 'Owner fact', 'pending_review')]
    with database() as db:
        audits = db.query(AuditRecord).filter(AuditRecord.action == 'credential.resolved').all()
        assert [a.metadata_json for a in audits] == [{'purpose': 'memory.capture'}]
        job = db.get(MemoryCaptureJobRecord, job_id)
        assert SECRET not in repr(job.__dict__) and SECRET not in str(job.actions)


def test_unsupported_protocol_is_skipped_without_calling_any_model(database, monkeypatch, deployment_config):  # noqa: F811
    principal, tenant, session, run, _ = stack(database)
    version_id = _owner_model(database, principal, tenant.id, deployment_config)
    _enable(database, principal, tenant.id, version_id)
    _messages(database, session.id, 4)
    job_id = UUID(_enqueue(database, run.id, utc_now()))
    # The native factory only builds the protocols a Run can use; anything else is a skip.
    monkeypatch.setattr(worker_capture, 'SUPPORTED_PROTOCOLS', ())

    def refuse(**kwargs):
        raise AssertionError('no model may be created for an unsupported protocol')
    monkeypatch.setattr(worker_capture, 'create_model', refuse)
    assert capture.run_due(database, owner_extractor(database), worker_id='w1',
                           now=utc_now() + timedelta(hours=1)) == 'completed'
    with database() as db:
        assert db.get(MemoryCaptureJobRecord, job_id).last_error == 'model_unavailable'


def test_worker_tick_waits_until_the_job_delay_has_passed(database, monkeypatch, deployment_config):  # noqa: F811
    principal, tenant, session, run, _ = stack(database)
    version_id = _owner_model(database, principal, tenant.id, deployment_config)
    _enable(database, principal, tenant.id, version_id)
    _messages(database, session.id, 4)
    _enqueue(database, run.id, utc_now())

    def refuse(**kwargs):
        raise AssertionError('the job is not due yet')
    monkeypatch.setattr(worker_capture, 'create_model', refuse)
    assert capture_tick(database, 'w1') is False
