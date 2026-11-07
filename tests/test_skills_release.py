"""Release of skills: scan, release policy, invocation flags and rescan (openspec 2026-11-07-skill-evolution, S1)."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from nexus_core.platform import SYSTEM_USER_ID
from nexus_platform.errors import Conflict, InvalidConfiguration, NotFound
from nexus_platform.persistence.models import AuditRecord, SkillVersionRecord
from nexus_platform.sessions.service import create_session
from nexus_platform.skills.service import (
    SkillScanBlocked, import_builtin_as, publish, read_for_run, rescan, session_index, skill_versions,
)
from nexus_skills.guard.scan import SCANNER_VERSION
from test_platform import database  # noqa: F401  (pytest fixture)
from test_skills_api import _client, teardown_function  # noqa: F401
from test_skills_platform import PRINCIPAL, SKILL, _agent, _publish, _tenant, _version_for

DANGEROUS = {'scripts/clean.sh': 'rm -rf ~\n'}
CAUTIOUS = {'scripts/fetch.py': 'import requests\n'}


def _md(name='release-skill', extra=''):
    return f'---\nname: {name}\ndescription: Release test\ntools: []\n{extra}---\nBody\n'


def _audit_actions(factory):
    with factory() as db:
        return [row.action for row in db.scalars(select(AuditRecord))]


def test_an_administrator_must_acknowledge_dangerous_findings(database):
    tenant, _ = _tenant(database)
    with database() as db, pytest.raises(SkillScanBlocked) as stopped:
        publish(db, PRINCIPAL, tenant.id, _md(), DANGEROUS)
    assert stopped.value.code == 'skill_ack_required'
    assert stopped.value.details['verdict'] == 'dangerous'
    assert stopped.value.details['findings'][0]['rule'] == 'wipe_root_or_home'
    with database() as db:
        result = publish(db, PRINCIPAL, tenant.id, _md(), DANGEROUS, acknowledge_findings=True)
    assert result['verdict'] == 'dangerous'
    assert 'skill.findings_acknowledged' in _audit_actions(database)
    versions = None
    with database() as db:
        versions = skill_versions(db, PRINCIPAL, tenant.id, 'release-skill')
    assert versions[0]['trust'] == 'admin' and versions[0]['verdict'] == 'dangerous'
    assert versions[0]['findings'][0]['path'] == 'scripts/clean.sh' and not versions[0]['rescan_needed']


def test_imported_skills_with_findings_are_blocked_until_released(database):
    tenant, _ = _tenant(database)
    with database() as db, pytest.raises(SkillScanBlocked) as stopped:
        publish(db, PRINCIPAL, tenant.id, _md(), CAUTIOUS, source='import')
    assert stopped.value.code == 'skill_scan_blocked'
    with database() as db:
        assert publish(db, PRINCIPAL, tenant.id, _md(), CAUTIOUS, source='import', acknowledge_findings=True)['version'] == 1
    with database() as db:
        assert skill_versions(db, PRINCIPAL, tenant.id, 'release-skill')[0]['trust'] == 'import'


def test_model_and_member_sources_go_to_review_or_are_refused(database):
    tenant, _ = _tenant(database)
    for source, files, code in (('agent', CAUTIOUS, 'skill_review_required'), ('agent', DANGEROUS, 'skill_scan_refused'),
                                ('user', {}, 'skill_review_required'), ('user', DANGEROUS, 'skill_scan_refused')):
        with database() as db, pytest.raises(SkillScanBlocked) as stopped:
            publish(db, PRINCIPAL, tenant.id, _md(name=f'{source}-skill'), files, source=source)
        assert stopped.value.code == code, (source, files)
        # Acknowledging never turns a refusal or a review request into a publish.
        with database() as db, pytest.raises(SkillScanBlocked):
            publish(db, PRINCIPAL, tenant.id, _md(name=f'{source}-skill'), files, source=source, acknowledge_findings=True)


def test_local_execution_is_for_builtin_skills_only(database, tmp_path):
    tenant, _ = _tenant(database)
    with database() as db, pytest.raises(InvalidConfiguration, match='skill_execution_not_permitted'):
        publish(db, PRINCIPAL, tenant.id, _md(extra='execution: local\n'), {})
    folder = tmp_path / 'host-skill'
    folder.mkdir()
    (folder / 'SKILL.md').write_text(_md(name='host-skill', extra='execution: local\n'), encoding='utf-8')
    with database() as db:
        results = import_builtin_as(db, SYSTEM_USER_ID, tmp_path)
    assert [(r['folder'], r['status']) for r in results] == [('host-skill', 'published')]
    with database() as db:
        row = db.scalar(select(SkillVersionRecord).where(SkillVersionRecord.execution == 'local'))
        assert row.trust == 'builtin'


def test_a_skill_hidden_from_the_model_is_neither_indexed_nor_readable(database):
    tenant, model_version = _tenant(database)
    shown = _publish(database, tenant)
    hidden = _publish(database, tenant, text=SKILL.replace('report-writer', 'hidden-skill') .replace(
        'tools: ["read_memory"]\n', 'tools: ["read_memory"]\nmodel_invocable: false\n'))
    agent_version_id = _version_for(database, tenant, _agent(database, tenant, model_version, [shown, hidden]))
    with database() as db:
        session_id = create_session(db, PRINCIPAL, tenant.id, agent_version_id=agent_version_id, title='S').id
    with database() as db:
        text = session_index(db, tenant.id, session_id, agent_version_id)
        db.commit()
    assert 'report-writer' in text and 'hidden-skill' not in text
    with database() as db:
        assert 'report-writer' in read_for_run(db, tenant.id, agent_version_id, 'report-writer')
        with pytest.raises(NotFound):
            read_for_run(db, tenant.id, agent_version_id, 'hidden-skill')


def test_unknown_frontmatter_keys_are_kept_and_reported(database):
    tenant, _ = _tenant(database)
    with database() as db:
        result = publish(db, PRINCIPAL, tenant.id, _md(extra='license: MIT\ncolour: red\n'), {})
    assert result['notes'] == ['frontmatter_key_unknown:colour']
    with database() as db:
        row = db.scalar(select(SkillVersionRecord))
        assert row.extra['values'] == {'license': 'MIT', 'colour': 'red'}


def test_rescan_stores_a_new_result_without_touching_content(database):
    tenant, _ = _tenant(database)
    with database() as db:
        published = publish(db, PRINCIPAL, tenant.id, _md(), CAUTIOUS)
    with database() as db, db.begin():
        row = db.scalar(select(SkillVersionRecord))
        row.scan_version, row.scan = 0, {}
    with database() as db:
        assert skill_versions(db, PRINCIPAL, tenant.id, 'release-skill')[0]['rescan_needed'] is True
    with database() as db:
        result = rescan(db, PRINCIPAL, tenant.id, 'release-skill', 1)
    assert result['verdict'] == 'caution' and result['scan_version'] == SCANNER_VERSION
    with database() as db:
        listed = skill_versions(db, PRINCIPAL, tenant.id, 'release-skill')[0]
        assert not listed['rescan_needed'] and listed['content_hash'] == published['content_hash']
    with database() as db, pytest.raises(NotFound):
        rescan(db, PRINCIPAL, tenant.id, 'release-skill', 9)


def test_the_http_error_carries_the_findings(database):
    tenant, _ = _tenant(database)
    client = _client(database, PRINCIPAL)
    base = f'/api/v1/tenants/{tenant.id}/skills'
    stopped = client.post(base, json={'skill_md': _md(), 'files': DANGEROUS})
    assert stopped.status_code == 422
    error = stopped.json()['error']
    assert error['code'] == 'skill_ack_required' and error['details']['findings'][0]['rule'] == 'wipe_root_or_home'
    released = client.post(base, json={'skill_md': _md(), 'files': DANGEROUS, 'acknowledge_findings': True})
    assert released.status_code == 201 and released.json()['verdict'] == 'dangerous'
    assert client.post(base + '/release-skill/versions/1/rescan').json()['verdict'] == 'dangerous'
