"""Skill install state machine and dependency environments (openspec 2026-11-07-skill-evolution, S3 3.4/3.5/3.7)."""
import io
import json
import subprocess
import zipfile
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from nexus_core.platform import utc_now
from nexus_platform.errors import Conflict, InvalidConfiguration, PlatformError
from nexus_platform.persistence.models import AuditRecord, SkillRecord, SkillVersionRecord
from nexus_platform.skills import install
from nexus_platform.skills.service import install_bundle, publish, skill_versions
from nexus_sandbox import build
from nexus_sandbox.build import BuildResult
from nexus_sandbox.settings import SandboxSettings
from test_platform import database  # noqa: F401  (pytest fixture)
from test_skills_platform import PRINCIPAL, _tenant

MD = '---\nname: needs-deps\ndescription: Has a manifest\ntools: []\n---\nBody\n'
PLAIN = '---\nname: needs-deps\ndescription: Without manifest\ntools: []\n---\nBody\n'
SANDBOX = '''
[sandbox]
enabled = true
allow_local = true
workspace_root = @ROOT@
[sandbox.profiles.local]
type = "local"
'''


def _zip(entries):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, content in entries:
            archive.writestr(name, content)
    return buffer.getvalue()


@pytest.fixture
def sandbox(monkeypatch, tmp_path):
    path = tmp_path / 'nexus.toml'
    path.write_text(SANDBOX.replace('@ROOT@', json.dumps(str(tmp_path / 'sbx'))), encoding='utf-8')
    monkeypatch.setattr('nexus_core.deployment.config_path', lambda: path)
    monkeypatch.setattr('nexus_platform.configuration.auth_settings', lambda *a, **k: SimpleNamespace(mode='development'))
    return tmp_path / 'sbx'


def _upload(database, tenant, manifest='requests\n', md=MD):
    with database() as db:
        return install_bundle(db, PRINCIPAL, tenant.id, _zip([('SKILL.md', md), ('requirements.txt', manifest)]))


def _state(database, version_id=None):
    with database() as db:
        row = db.scalar(select(SkillVersionRecord).order_by(SkillVersionRecord.version.desc()))
        return row.build_state, row.build_error


def _pointer(database, name='needs-deps'):
    with database() as db:
        return db.scalar(select(SkillRecord.current_version_id).where(SkillRecord.name == name))


def _fake_build(monkeypatch, result=None, create_env=True, hook=None):
    async def fake(settings, staging, files, *, job):
        if hook:
            hook()
        if create_env:
            (staging / 'env').mkdir(parents=True, exist_ok=True)
            (staging / 'env' / 'installed.json').write_text(json.dumps([{'name': 'Requests', 'version': '1'}]))
            (staging / 'env' / 'marker').write_text('built')
        return result or BuildResult(True, '', 'built')
    monkeypatch.setattr(install.build, 'build_environment', fake)


# ---- state machine ----------------------------------------------------------------------------------------

def test_a_version_with_a_manifest_waits_unserved_until_the_worker_builds_it(database, sandbox, monkeypatch):
    tenant, _ = _tenant(database)
    result = _upload(database, tenant)
    assert result['build_state'] == 'installing'
    assert _pointer(database) is None  # a new skill is not served yet
    _fake_build(monkeypatch)
    assert install.tick(database) is True
    assert _state(database) == ('ready', None)
    assert _pointer(database) is not None
    with database() as db:
        row = db.scalar(select(SkillVersionRecord))
        assert row.env_ref and (sandbox / '_skill_envs' / 'local' / row.env_ref / 'marker').read_text() == 'built'
        assert not (sandbox / '_skill_envs' / 'local' / row.env_ref / 'installed.json').exists()
        assert not (sandbox / '_staging' / str(row.id)).exists()
        actions = [a.action for a in db.scalars(select(AuditRecord))]
    assert 'skill.install_started' in actions and 'skill.published' in actions
    assert install.tick(database) is False  # nothing left to do


def test_a_failed_build_keeps_the_previous_version_serving(database, sandbox, monkeypatch):
    tenant, _ = _tenant(database)
    with database() as db:
        first = install_bundle(db, PRINCIPAL, tenant.id, _zip([('SKILL.md', PLAIN)]))
    _upload(database, tenant)
    _fake_build(monkeypatch, BuildResult(False, 'build_failed', 'ERROR: no matching distribution'), create_env=False)
    install.tick(database)
    assert _state(database) == ('failed', 'build_failed')
    assert str(_pointer(database)) == first['version_id']
    with database() as db:
        info = install.status(db, PRINCIPAL, tenant.id, 'needs-deps', 2)
        assert info['build_error'] == 'build_failed' and 'no matching distribution' in info['build_log']
        assert [v['build_state'] for v in skill_versions(db, PRINCIPAL, tenant.id, 'needs-deps')] == ['ready', 'failed']
    assert not list((sandbox / '_staging').glob('*'))  # staging is gone on the failure path too


def test_a_package_the_build_did_not_report_fails_verification(database, sandbox, monkeypatch):
    tenant, _ = _tenant(database)
    _upload(database, tenant, manifest='requests\nnot-there>=1\n')
    _fake_build(monkeypatch)
    install.tick(database)
    assert _state(database) == ('failed', 'verify_failed:not_installed:not-there')


def test_an_exception_in_the_build_becomes_a_failed_version(database, sandbox, monkeypatch):
    tenant, _ = _tenant(database)
    _upload(database, tenant)

    async def broken(*args, **kwargs):
        raise RuntimeError('boom')
    monkeypatch.setattr(install.build, 'build_environment', broken)
    install.tick(database)
    assert _state(database) == ('failed', 'build_internal_error')


def test_only_one_install_per_skill_and_reinstall_reuses_the_stored_zip(database, sandbox, monkeypatch):
    tenant, _ = _tenant(database)
    _upload(database, tenant)
    with database() as db, pytest.raises(Conflict, match='skill_install_in_progress'):
        install_bundle(db, PRINCIPAL, tenant.id, _zip([('SKILL.md', MD), ('requirements.txt', 'other\n')]))
    _fake_build(monkeypatch, BuildResult(False, 'build_timeout', 'slow'), create_env=False)
    install.tick(database)
    _fake_build(monkeypatch)
    with database() as db:
        assert install.reinstall(db, PRINCIPAL, tenant.id, 'needs-deps', 1)['build_state'] == 'installing'
    install.tick(database)
    assert _state(database) == ('ready', None)
    with database() as db, pytest.raises(Conflict, match='skill_already_installed'):
        install.reinstall(db, PRINCIPAL, tenant.id, 'needs-deps', 1)


def test_reinstall_needs_dependencies_and_an_administrator(database, sandbox):
    tenant, _ = _tenant(database)
    with database() as db:
        install_bundle(db, PRINCIPAL, tenant.id, _zip([('SKILL.md', PLAIN)]))
    with database() as db, pytest.raises(InvalidConfiguration, match='skill_has_no_dependencies'):
        install.reinstall(db, PRINCIPAL, tenant.id, 'needs-deps', 1, 'local')


def test_stopping_an_install_ends_it_and_a_running_build_gives_way(database, sandbox, monkeypatch):
    tenant, _ = _tenant(database)
    _upload(database, tenant)

    def stop_midway():
        with database() as db:
            install.stop(db, PRINCIPAL, tenant.id, 'needs-deps', 1)
    _fake_build(monkeypatch, hook=stop_midway)
    claimed = install.claim(database)
    assert claimed is not None and install.run_build(database, claimed) == 'cancelled'
    assert _state(database) == ('failed', 'install_stopped') and _pointer(database) is None
    with database() as db, pytest.raises(Conflict, match='skill_not_installing'):
        install.stop(db, PRINCIPAL, tenant.id, 'needs-deps', 1)


def test_one_worker_claims_a_row_and_a_second_gets_nothing(database, sandbox):
    tenant, _ = _tenant(database)
    _upload(database, tenant)
    first = install.claim(database)
    assert first is not None and install.claim(database) is None


def test_a_build_that_lost_its_worker_is_failed_and_leftovers_are_removed(database, sandbox, monkeypatch):
    tenant, _ = _tenant(database)
    _upload(database, tenant)
    version_id = install.claim(database)
    orphan = sandbox / '_staging' / 'leftover'
    orphan.mkdir(parents=True)
    live = sandbox / '_staging' / str(version_id)
    live.mkdir()
    old_env = sandbox / '_skill_envs' / 'local' / 'old-env'
    old_env.mkdir(parents=True)
    import os
    os.utime(old_env, (1, 1))
    assert install.reap(database)['interrupted'] == 0  # the heartbeat is fresh
    assert not orphan.exists() and live.exists() and not old_env.exists()
    with database() as db, db.begin():
        db.get(SkillVersionRecord, version_id).build_heartbeat_at = utc_now() - timedelta(hours=1)
    counts = install.reap(database)
    assert counts['interrupted'] == 1 and _state(database) == ('failed', 'build_interrupted')
    assert not live.exists()


def test_environments_of_ready_versions_are_never_removed(database, sandbox, monkeypatch):
    tenant, _ = _tenant(database)
    _upload(database, tenant)
    _fake_build(monkeypatch)
    install.tick(database)
    with database() as db:
        env = sandbox / '_skill_envs' / 'local' / db.scalar(select(SkillVersionRecord.env_ref))
    import os
    os.utime(env, (1, 1))
    install.reap(database)
    assert env.is_dir()


# ---- command lines and mounts -----------------------------------------------------------------------------

def test_the_build_script_covers_python_and_node_manifests():
    script = build.build_script({'requirements.txt', 'package.json', 'package-lock.json'}, '/env', '/in')
    assert script.startswith('set -e') and 'venv /env/venv' in script.replace('-m venv ', 'venv ')
    assert 'pip install' in script and '-r /in/requirements.txt' in script and 'pip list --format=json' in script
    assert 'npm install' in script and 'cp /in/package-lock.json /env/node/' in script
    assert build.build_script({'requirements.txt'}, '/env', '/in').count('npm') == 0


def test_the_docker_build_container_is_labelled_unprivileged_and_on_the_install_network(tmp_path):
    settings = SandboxSettings(backend='docker', image='python:3.12-slim', install_network='bridge', profile='docker')
    args = build.docker_arguments(settings, 'nexus-build-x', tmp_path / 'env', tmp_path / 'in', 'echo', 'job1')
    joined = ' '.join(args)
    assert '--rm' in args and 'nexus.sandbox.build=1' in joined and '--network bridge' in joined
    assert '--cap-drop ALL' in joined and 'no-new-privileges' in joined and '--read-only' in args
    assert f'{(tmp_path / "in").resolve()}:/in:ro' in joined and f'{(tmp_path / "env").resolve()}:/env' in joined
    assert args[-4:] == ['python:3.12-slim', 'sh', '-c', 'echo']


def test_the_bwrap_build_jail_opens_the_network_and_only_env_is_writable(tmp_path):
    args = build.bwrap_arguments(SandboxSettings(backend='bwrap'), tmp_path / 'env', tmp_path / 'in', 'echo')
    assert '--share-net' in args and '--cap-drop' in args and '--remount-ro' in args
    assert args[args.index('--bind') + 2] == '/env' and '--ro-bind' in args
    assert args.count('--bind') == 1  # nothing else is writable


def test_run_time_containers_mount_environments_read_only(tmp_path):
    from nexus_sandbox.backends.bwrap import BwrapBackend
    from nexus_sandbox.backends.docker import DockerBackend
    settings = SandboxSettings(backend='docker', profile='docker')
    run = DockerBackend(settings).run_arguments('n', tmp_path / 'w', tmp_path / 'o', tmp_path / 's', tmp_path / 'e')
    assert f'{(tmp_path / "e").resolve()}:/skill_envs:ro' in run
    jail = BwrapBackend(SandboxSettings(backend='bwrap')).jail_arguments(tmp_path / 'w', tmp_path / 'o', '/workspace', 'x',
                                                                         None, tmp_path / 's', tmp_path / 'e')
    at = jail.index('/skill_envs')
    assert jail[at - 2] == '--ro-bind'


def test_environment_names_depend_on_content_and_environment(tmp_path):
    docker_a = SandboxSettings(backend='docker', image='a:1')
    docker_b = SandboxSettings(backend='docker', image='b:1')
    assert build.environment_name('a' * 64, docker_a) != build.environment_name('a' * 64, docker_b)
    assert build.environment_name('a' * 64, docker_a) != build.environment_name('b' * 64, docker_a)
    assert build.environment_name('a' * 64, docker_a).startswith('a' * 16 + '-')


def test_a_script_command_puts_the_environment_first_on_path():
    from nexus_skills.exec import build_command
    command = build_command('python3', '/skills/s@h', 'scripts/a.py', ['x y'], '/skill_envs/e/venv/bin:/skill_envs/e/node/node_modules/.bin')
    assert command.startswith('PATH=/skill_envs/e/venv/bin:/skill_envs/e/node/node_modules/.bin:"$PATH" python3 ')
    assert build_command('python3', '/s', 'a.py', []) == 'python3 /s/a.py'


# ---- a real build on the host (local profile) ---------------------------------------------------------------

def _wheel(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(directory / 'nexusdemo-1.0-py3-none-any.whl', 'w') as wheel:
        wheel.writestr('nexusdemo/__init__.py', 'VALUE = 42\n')
        wheel.writestr('nexusdemo-1.0.dist-info/METADATA', 'Metadata-Version: 2.1\nName: nexusdemo\nVersion: 1.0\n')
        wheel.writestr('nexusdemo-1.0.dist-info/WHEEL',
                       'Wheel-Version: 1.0\nGenerator: test\nRoot-Is-Purelib: true\nTag: py3-none-any\n')
        wheel.writestr('nexusdemo-1.0.dist-info/RECORD', '')


def test_a_real_local_build_installs_a_package_and_survives_the_move(database, sandbox, monkeypatch, tmp_path):
    _wheel(tmp_path / 'wheels')
    monkeypatch.setenv('PIP_NO_INDEX', '1')
    monkeypatch.setenv('PIP_FIND_LINKS', str(tmp_path / 'wheels'))
    tenant, _ = _tenant(database)
    _upload(database, tenant, manifest='nexusdemo==1.0\n')
    assert install.tick(database) is True
    state = _state(database)
    assert state == ('ready', None), state
    with database() as db:
        env = sandbox / '_skill_envs' / 'local' / db.scalar(select(SkillVersionRecord.env_ref))
    python = env / 'venv' / 'bin' / 'python'
    done = subprocess.run([str(python), '-c', 'import nexusdemo; print(nexusdemo.VALUE)'], capture_output=True, text=True)
    assert done.stdout.strip() == '42', done.stderr  # the environment still works after the rename into place


def test_a_real_local_build_failure_is_reported_with_the_pip_output(database, sandbox, monkeypatch, tmp_path):
    (tmp_path / 'empty').mkdir()
    monkeypatch.setenv('PIP_NO_INDEX', '1')
    monkeypatch.setenv('PIP_FIND_LINKS', str(tmp_path / 'empty'))
    tenant, _ = _tenant(database)
    _upload(database, tenant, manifest='no-such-package-xyz==9\n')
    install.tick(database)
    assert _state(database) == ('failed', 'build_failed')
    with database() as db:
        assert 'no-such-package-xyz' in install.status(db, PRINCIPAL, tenant.id, 'needs-deps', 1)['build_log']
