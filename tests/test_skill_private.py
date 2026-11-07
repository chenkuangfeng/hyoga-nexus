"""Private skills and drafts (openspec 2026-11-07-skill-evolution, S4 4.1/4.2/4.4/4.5/4.8)."""
import json
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from nexus_core.platform import Principal
from nexus_platform.errors import Conflict, InvalidConfiguration, NotFound
from nexus_platform.identity.service import resolve_user
from nexus_platform.models.provider_settings import context
from nexus_platform.persistence.models import AuditRecord, PlatformResourceRecord, SkillRecord, SkillVersionRecord
from nexus_platform.sessions.service import create_session
from nexus_platform.skills import private
from nexus_platform.skills.service import (
    SkillScanBlocked, publish, read_for_run, session_index, skill_files,
)
from test_platform import database  # noqa: F401  (pytest fixture)
from test_skills_platform import PRINCIPAL, _agent, _tenant, _version_for

MD = '---\nname: my-notes\ndescription: Keeps my notes tidy\ntools: []\n---\n# Steps\nWrite short notes.\n'


@pytest.fixture
def ids(database):
    tenant, model_version = _tenant(database)
    with database() as db:
        with db.begin():
            alice = context(db, PRINCIPAL, tenant.id)[0].id
    return tenant, model_version, alice


def _do(database, fn, *args, **kwargs):
    with database() as db, db.begin():
        return fn(db, *args, **kwargs)


def _save(database, tenant, user, md=MD, files=None, name='my-notes', profile=None):
    _do(database, private.create, tenant.id, user, md, files or {})
    return _do(database, private.save, tenant.id, user, name, profile=profile)


def test_a_draft_becomes_a_live_private_skill_that_is_not_a_platform_resource(database, ids):
    tenant, _, alice = ids
    created = _do(database, private.create, tenant.id, alice, MD, {'refs/a.md': 'one'})
    assert created['created'] and created['files'] == ['refs/a.md']
    saved = _do(database, private.save, tenant.id, alice, 'my-notes')
    assert saved['version'] == 1 and saved['build_state'] == 'ready'
    with database() as db:
        skill = db.scalar(select(SkillRecord).where(SkillRecord.name == 'my-notes'))
        assert skill.owner_user_id == alice and skill.current_version_id is not None and skill.source == 'private'
        assert db.scalar(select(PlatformResourceRecord).where(PlatformResourceRecord.resource_id == 'my-notes')) is None
        assert private.listing(db, tenant.id, alice)['drafts'] == []  # saving consumes the draft


def test_the_owner_sees_the_skill_in_the_index_and_can_read_it_and_nobody_else_can(database, ids):
    tenant, model_version, alice = ids
    _save(database, tenant, alice, files={'refs/a.md': 'one'})
    agent_version_id = _version_for(database, tenant, _agent(database, tenant, model_version, []))
    with database() as db:
        session_id = create_session(db, PRINCIPAL, tenant.id, agent_version_id=agent_version_id, title='S').id
        bob = resolve_user(db, Principal(id='bob', issuer='test')).id
    with database() as db:
        assert 'my-notes | Keeps my notes tidy' in session_index(db, tenant.id, session_id, agent_version_id, alice)
        db.rollback()
    with database() as db:
        assert 'Write short notes' in read_for_run(db, tenant.id, agent_version_id, 'my-notes', user_id=alice)
        assert 'one' in read_for_run(db, tenant.id, agent_version_id, 'my-notes', 'refs/a.md', user_id=alice)
        assert skill_files(db, tenant.id, agent_version_id, 'my-notes', user_id=alice) is not None
        for stranger in (bob, None):
            with pytest.raises(NotFound):
                read_for_run(db, tenant.id, agent_version_id, 'my-notes', user_id=stranger)
            assert skill_files(db, tenant.id, agent_version_id, 'my-notes', user_id=stranger) is None
    with database() as db:
        assert private.visible_versions(db, tenant.id, bob) == {}


def test_guards_follow_the_hermes_rules(database, ids):
    tenant, _, alice = ids
    _do(database, private.create, tenant.id, alice, MD + '\nsame line\nsame line\n')
    viewed: set[str] = set()
    with pytest.raises(InvalidConfiguration, match='skill_draft_unread'):  # edits need a view in this Run first
        _do(database, private.patch, tenant.id, alice, 'my-notes', 'short', 'long', viewed=viewed)
    _do(database, private.view, tenant.id, alice, 'my-notes', viewed=viewed)
    with pytest.raises(InvalidConfiguration, match='skill_patch_ambiguous'):
        _do(database, private.patch, tenant.id, alice, 'my-notes', 'same line', 'x', viewed=viewed)
    with pytest.raises(InvalidConfiguration, match='skill_patch_not_found'):
        _do(database, private.patch, tenant.id, alice, 'my-notes', 'absent', 'x', viewed=viewed)
    done = _do(database, private.patch, tenant.id, alice, 'my-notes', 'same line', 'x', replace_all=True, viewed=viewed)
    assert done['name'] == 'my-notes'
    with pytest.raises(InvalidConfiguration, match='skill_name_immutable'):
        _do(database, private.patch, tenant.id, alice, 'my-notes', 'name: my-notes', 'name: other', viewed=viewed)
    for bad in ('notes.md', '../x.md', 'scripts/.hidden', '/abs.md', 'SKILL.md.bak'):
        with pytest.raises(InvalidConfiguration):
            _do(database, private.write_file, tenant.id, alice, 'my-notes', bad, 'x', viewed=viewed)
    _do(database, private.write_file, tenant.id, alice, 'my-notes', 'templates/t.md', 'hello', viewed=viewed)
    _do(database, private.remove_file, tenant.id, alice, 'my-notes', 'templates/t.md', viewed=viewed)
    with pytest.raises(NotFound):
        _do(database, private.remove_file, tenant.id, alice, 'my-notes', 'templates/t.md', viewed=viewed)


def test_names_are_unique_across_private_library_and_builtin(database, ids):
    tenant, _, alice = ids
    with database() as db:
        publish(db, PRINCIPAL, tenant.id, MD.replace('my-notes', 'shared-one'), {})
    with pytest.raises(InvalidConfiguration, match='skill_name_taken'):
        _do(database, private.create, tenant.id, alice, MD.replace('my-notes', 'shared-one'))
    _do(database, private.create, tenant.id, alice, MD)
    with pytest.raises(Conflict, match='skill_draft_exists'):
        _do(database, private.create, tenant.id, alice, MD)


def test_limits_on_drafts_and_size(database, ids, monkeypatch):
    tenant, _, alice = ids
    monkeypatch.setattr(private, 'DRAFT_LIMIT', 2)
    _do(database, private.create, tenant.id, alice, MD.replace('my-notes', 'one'))
    _do(database, private.create, tenant.id, alice, MD.replace('my-notes', 'two'))
    with pytest.raises(InvalidConfiguration, match='skill_draft_limit'):
        _do(database, private.create, tenant.id, alice, MD.replace('my-notes', 'three'))
    monkeypatch.setattr(private, 'TOTAL_BYTES', 400)
    with pytest.raises(InvalidConfiguration, match='skill_draft_too_large'):
        _do(database, private.write_file, tenant.id, alice, 'one', 'refs/big.md', 'x' * 500, viewed={'one'})


def test_a_dangerous_skill_is_refused_and_a_clean_one_goes_live(database, ids, monkeypatch):
    monkeypatch.setattr('nexus_platform.skills.service.sandbox_can_build', lambda profile: True)
    tenant, _, alice = ids
    _do(database, private.create, tenant.id, alice, MD, {'refs/x.md': 'r'})
    _do(database, private.write_file, tenant.id, alice, 'my-notes', 'scripts/clean.sh', 'rm -rf ~\n')
    with database() as db, pytest.raises(SkillScanBlocked) as stopped:
        with db.begin():
            private.save(db, tenant.id, alice, 'my-notes')
    assert stopped.value.code == 'skill_scan_refused'
    with database() as db:
        assert db.scalar(select(SkillVersionRecord)) is None
    _do(database, private.remove_file, tenant.id, alice, 'my-notes', 'scripts/clean.sh')
    assert _do(database, private.save, tenant.id, alice, 'my-notes')['build_state'] == 'ready'


def test_editing_a_saved_skill_starts_from_its_current_version_and_a_moved_base_is_refused(database, ids):
    tenant, _, alice = ids
    _save(database, tenant, alice, files={'refs/a.md': 'one'})
    viewed: set[str] = set()
    seeded = _do(database, private.view, tenant.id, alice, 'my-notes', viewed=viewed)
    assert seeded['files'] == ['refs/a.md']
    _do(database, private.patch, tenant.id, alice, 'my-notes', 'short notes', 'brief notes', viewed=viewed)
    # Another session saves first, so this draft's base is stale.
    with database() as db, db.begin():
        skill = private.private_skill(db, tenant.id, alice, 'my-notes')
        skill.current_version_id = skill.current_version_id  # unchanged pointer, changed content below
        draft = db.get(private.SkillDraftRecord, (tenant.id, alice, 'my-notes'))
        draft.base_hash = 'f' * 64
    with pytest.raises(Conflict, match='skill_base_changed'):
        _do(database, private.save, tenant.id, alice, 'my-notes')
    with database() as db, db.begin():
        db.get(private.SkillDraftRecord, (tenant.id, alice, 'my-notes')).base_hash = db.scalar(
            select(SkillVersionRecord.content_hash))
    assert _do(database, private.save, tenant.id, alice, 'my-notes')['version'] == 2


def test_saving_unchanged_content_creates_no_new_version(database, ids):
    tenant, _, alice = ids
    _save(database, tenant, alice)
    _do(database, private.view, tenant.id, alice, 'my-notes')
    assert _do(database, private.save, tenant.id, alice, 'my-notes') == {'skill': 'my-notes', 'unchanged': True}


def test_binary_files_the_draft_never_touched_keep_their_bytes(database, ids):
    import io, zipfile
    from nexus_platform.skills.service import install_bundle
    tenant, _, alice = ids
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        archive.writestr('SKILL.md', MD)
        archive.writestr('assets/logo.png', b'\x89PNG\x00\x01\x02')
    # Seed a private skill that carries a binary file (an upload path for private skills comes with the "my skills" page).
    with database() as db, db.begin():
        from nexus_platform.skills.service import _publish_version
        from nexus_skills import bundle
        unpacked = bundle.unpack(buffer.getvalue())
        _publish_version(db, tenant.id, alice, unpacked.skill_md, unpacked.text, 'private', binary=unpacked.binary,
                         owner_user_id=alice)
    viewed: set[str] = set()
    _do(database, private.view, tenant.id, alice, 'my-notes', viewed=viewed)
    _do(database, private.patch, tenant.id, alice, 'my-notes', 'short notes', 'brief notes', viewed=viewed)
    assert _do(database, private.save, tenant.id, alice, 'my-notes')['binary_files'] == ['assets/logo.png']
    with database() as db:
        newest = db.scalar(select(SkillVersionRecord).order_by(SkillVersionRecord.version.desc()))
        from nexus_skills import bundle
        assert bundle.unpack(newest.bundle).binary == {'assets/logo.png': b'\x89PNG\x00\x01\x02'}


def test_rollback_archive_restore_and_supersede(database, ids):
    tenant, model_version, alice = ids
    _save(database, tenant, alice)
    viewed: set[str] = set()
    _do(database, private.view, tenant.id, alice, 'my-notes', viewed=viewed)
    _do(database, private.patch, tenant.id, alice, 'my-notes', 'short notes', 'brief notes', viewed=viewed)
    _do(database, private.save, tenant.id, alice, 'my-notes')
    with database() as db:
        assert [v['current'] for v in private.versions(db, tenant.id, alice, 'my-notes')] == [False, True]
    _do(database, private.rollback, tenant.id, alice, 'my-notes', 1)
    with database() as db:
        assert [v['current'] for v in private.versions(db, tenant.id, alice, 'my-notes')] == [True, False]
        assert 'Write short notes' in next(iter(private.visible_versions(db, tenant.id, alice).values())).body
    with pytest.raises(NotFound):
        _do(database, private.rollback, tenant.id, alice, 'my-notes', 9)
    _do(database, private.archive, tenant.id, alice, 'my-notes')
    with database() as db:
        assert private.visible_versions(db, tenant.id, alice) == {}
        assert private.listing(db, tenant.id, alice)['skills'][0]['archived'] is True
    _do(database, private.restore, tenant.id, alice, 'my-notes')
    with database() as db:
        assert 'my-notes' in private.visible_versions(db, tenant.id, alice)
    with database() as db:  # the library later publishes the same name: the library skill answers to it
        publish(db, PRINCIPAL, tenant.id, MD, {})
    with database() as db:
        assert private.visible_versions(db, tenant.id, alice) == {}
        assert private.listing(db, tenant.id, alice)['skills'][0]['superseded'] is True
    with database() as db:
        assert {a.action for a in db.scalars(select(AuditRecord))} >= {'skill.rolled_back', 'skill.archived', 'skill.restored'}


def test_scripts_need_a_sandbox_that_can_run_them(database, ids, tmp_path, monkeypatch):
    tenant, _, alice = ids
    _do(database, private.create, tenant.id, alice, MD, {'scripts/go.py': 'print(1)\n'})
    with pytest.raises(InvalidConfiguration, match='skill_sandbox_required'):
        _do(database, private.save, tenant.id, alice, 'my-notes')
    path = tmp_path / 'nexus.toml'
    path.write_text(f'[sandbox]\nenabled = true\nallow_local = true\nworkspace_root = {json.dumps(str(tmp_path / "sbx"))}\n'
                    '[sandbox.profiles.local]\ntype = "local"\n', encoding='utf-8')
    monkeypatch.setattr('nexus_core.deployment.config_path', lambda: path)
    monkeypatch.setattr('nexus_platform.configuration.auth_settings', lambda *a, **k: SimpleNamespace(mode='development'))
    assert _do(database, private.save, tenant.id, alice, 'my-notes', profile='local')['build_state'] == 'ready'


def test_the_same_private_name_may_belong_to_two_users(database, ids):
    tenant, _, alice = ids
    with database() as db:
        bob = resolve_user(db, Principal(id='bob', issuer='test')).id
        db.commit()
    _save(database, tenant, alice)
    _do(database, private.create, tenant.id, bob, MD)
    assert _do(database, private.save, tenant.id, bob, 'my-notes')['version'] == 1
    with database() as db:
        assert len(db.scalars(select(SkillRecord).where(SkillRecord.name == 'my-notes')).all()) == 2


def test_my_skills_over_http_are_only_the_callers(database, ids):
    from test_skills_api import _client, teardown_function  # noqa: F401
    tenant, _, alice = ids
    _save(database, tenant, alice)
    base = f'/api/v1/tenants/{tenant.id}'
    http = _client(database, PRINCIPAL)
    mine = http.get(base + '/my-skills').json()
    assert [s['name'] for s in mine['skills']] == ['my-notes'] and mine['drafts'] == []
    assert http.get(base + '/skills').json() == []  # the library list never shows private skills
    assert http.get(base + '/my-skills/my-notes/versions').json()[0]['current'] is True
    assert http.post(base + '/my-skills/my-notes/rollback', json={'version': 5}).status_code == 404
    assert http.post(base + '/my-skills/my-notes/archive').json()['archived'] is True
    assert http.post(base + '/my-skills/my-notes/restore').json()['archived'] is False
    _do(database, private.create, tenant.id, alice, MD.replace('my-notes', 'scratch'))
    assert http.delete(base + '/my-skill-drafts/scratch').json()['deleted'] is True
    stranger = _client(database, Principal(id='mallory', issuer='test'))
    assert stranger.get(base + '/my-skills').status_code in (403, 404)
