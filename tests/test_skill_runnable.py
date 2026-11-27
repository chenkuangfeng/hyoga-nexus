"""Whether a skill's scripts can run on a sandbox profile, as the skill list reports it
(openspec 2026-11-07-skill-evolution, S2): the same rules `exec_skill` applies, answered before a Run."""
import json
from types import SimpleNamespace

import pytest

from nexus_core.platform import SYSTEM_USER_ID
from nexus_platform.skills.service import import_builtin_as, list_skills, publish
from nexus_sandbox import acceptance
from nexus_sandbox.settings import load_settings
from test_platform import database  # noqa: F401  (pytest fixture)
from test_skills_platform import PRINCIPAL, _tenant

SCRIPTED = '---\nname: scripted\ndescription: Has a script\ntools: []\n---\nBody\n'
PLAIN = '---\nname: plain\ndescription: Only words\ntools: []\n---\nBody\n'


def _deployment(monkeypatch, tmp_path, body, mode='development'):
    path = tmp_path / 'nexus.toml'
    path.write_text(body.replace('@ROOT@', json.dumps(str(tmp_path / 'sbx'))), encoding='utf-8')
    monkeypatch.setattr('nexus_core.deployment.config_path', lambda: path)
    monkeypatch.setattr('nexus_platform.configuration.auth_settings', lambda *a, **k: SimpleNamespace(mode=mode))
    if 'allow_local = true' in body:
        settings = load_settings(path, 'local')
        acceptance.FileReportStore().save(settings, {'passed': True, 'fingerprint': acceptance.fingerprint(settings)})
    return path


PROFILES = '''
[sandbox]
enabled = true
allow_local = true
workspace_root = @ROOT@
[sandbox.profiles.local]
type = "local"
[sandbox.profiles.docker]
type = "docker"
'''


def _runs(database, tenant, profile):
    with database() as db:
        return {row['name']: row['run'] for row in list_skills(db, PRINCIPAL, tenant.id, profile)}


@pytest.fixture
def space(database):
    tenant, _ = _tenant(database)
    with database() as db:
        publish(db, PRINCIPAL, tenant.id, SCRIPTED, {'scripts/go.py': 'print(1)'})
        publish(db, PRINCIPAL, tenant.id, PLAIN, {'refs/a.md': 'words'})
    return tenant


def test_without_a_profile_the_list_carries_no_answer(database, space):
    with database() as db:
        assert all(row['run'] is None for row in list_skills(db, PRINCIPAL, space.id))


def test_a_skill_without_scripts_has_nothing_to_say(database, space, monkeypatch, tmp_path):
    _deployment(monkeypatch, tmp_path, PROFILES)
    assert _runs(database, space, 'local')['plain'] is None


def test_when_the_sandbox_is_off_scripts_cannot_run(database, space, monkeypatch, tmp_path):
    _deployment(monkeypatch, tmp_path, '[sandbox]\nenabled = false')
    assert _runs(database, space, '')['scripted'] == {'ok': False, 'reason': 'sandbox_disabled'}


def test_an_unknown_profile_is_named(database, space, monkeypatch, tmp_path):
    _deployment(monkeypatch, tmp_path, PROFILES)
    assert _runs(database, space, 'ghost')['scripted'] == {'ok': False, 'reason': 'sandbox_profile_unknown'}


def test_a_container_profile_needs_a_passed_isolation_check(database, space, monkeypatch, tmp_path):
    path = _deployment(monkeypatch, tmp_path, PROFILES)
    assert _runs(database, space, 'docker')['scripted'] == {'ok': False, 'reason': 'sandbox_not_accepted'}
    settings = load_settings(path, 'docker')
    report = acceptance.report_path(settings)
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps({'passed': True, 'fingerprint': acceptance.fingerprint(settings)}), encoding='utf-8')
    assert _runs(database, space, 'docker')['scripted'] == {'ok': True, 'reason': ''}


def test_a_local_profile_runs_scripts_in_production_after_isolation_acceptance(database, space, monkeypatch, tmp_path):
    _deployment(monkeypatch, tmp_path, PROFILES)
    assert _runs(database, space, 'local')['scripted'] == {'ok': True, 'reason': ''}
    _deployment(monkeypatch, tmp_path, PROFILES, mode='production')
    assert _runs(database, space, 'local')['scripted'] == {'ok': True, 'reason': ''}


def test_the_empty_profile_means_the_default_one(database, space, monkeypatch, tmp_path):
    _deployment(monkeypatch, tmp_path, PROFILES.replace('allow_local = true', 'allow_local = true\ndefault_profile = "docker"'))
    assert _runs(database, space, '')['scripted']['reason'] == 'sandbox_not_accepted'  # the default is the docker profile


def test_a_builtin_skill_that_wants_the_host_follows_the_deployment_switch(database, space, monkeypatch, tmp_path):
    folder = tmp_path / 'builtin' / 'hostly'
    (folder / 'scripts').mkdir(parents=True)
    (folder / 'SKILL.md').write_text('---\nname: hostly\ndescription: Needs the host\nexecution: local\n---\nBody\n', encoding='utf-8')
    (folder / 'scripts' / 'hi.sh').write_text('echo hi\n', encoding='utf-8')
    with database() as db:
        import_builtin_as(db, SYSTEM_USER_ID, tmp_path / 'builtin')
    _deployment(monkeypatch, tmp_path, PROFILES)
    assert _runs(database, space, 'local')['hostly'] == {'ok': False, 'reason': 'local_not_allowed'}  # switch is off
    assert _runs(database, space, 'docker')['hostly'] == {'ok': False, 'reason': 'local_not_allowed'}  # never moved to a container
    _deployment(monkeypatch, tmp_path, PROFILES.replace('allow_local = true', 'allow_local = true\nallow_local_scripts = true'))
    assert _runs(database, space, 'local')['hostly'] == {'ok': True, 'reason': ''}
