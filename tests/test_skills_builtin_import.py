"""Builtin skills live in the system space and are assignable in every space (openspec 2026-11-07-skill-evolution, S1).

Imported skills get the builtin source, so a space skill with the same name cannot be created, and running the
import again reports unchanged folders instead of failing. Only platform administrators may import.
"""
from pathlib import Path

import pytest
from sqlalchemy import select

from nexus_core.platform import SYSTEM_TENANT_ID, SYSTEM_USER_ID
from nexus_platform.errors import Forbidden, InvalidConfiguration
from nexus_platform.persistence.models import SkillRecord, UserRecord
from nexus_platform.skills.service import import_builtin, import_builtin_as, list_skills, publish
from test_platform import database  # noqa: F401  (pytest fixture)
from test_skills_platform import PRINCIPAL, _tenant

ROOT = Path(__file__).resolve().parent.parent / 'skills' / 'general'


def _make_platform_admin(factory):
    with factory() as db:
        with db.begin():
            from nexus_platform.identity.service import resolve_user
            resolve_user(db, PRINCIPAL).is_platform_admin = True


def test_only_platform_administrators_may_import(database):
    _tenant(database)
    with database() as db, pytest.raises(Forbidden):
        import_builtin(db, PRINCIPAL, ROOT)


def test_import_publishes_example_skills_to_the_system_space_and_is_repeatable(database):
    _tenant(database)
    _make_platform_admin(database)
    with database() as db:
        first = import_builtin(db, PRINCIPAL, ROOT)
    assert sorted(r['folder'] for r in first) == ['text-stats', 'weekly-report']
    assert all(r['status'] == 'published' and r['version'] == 1 for r in first)
    with database() as db:
        assert {s.tenant_id for s in db.scalars(select(SkillRecord))} == {SYSTEM_TENANT_ID}
        assert db.get(UserRecord, SYSTEM_USER_ID).status == 'disabled'
    with database() as db:
        second = import_builtin(db, PRINCIPAL, ROOT)
    assert all(r['status'] == 'unchanged' for r in second)


def test_builtin_skills_are_listed_in_every_space(database):
    tenant, _ = _tenant(database)
    _make_platform_admin(database)
    with database() as db:
        import_builtin(db, PRINCIPAL, ROOT)
    with database() as db:
        rows = list_skills(db, PRINCIPAL, tenant.id)
    builtin = {r['name']: r for r in rows if r['scope'] == 'builtin'}
    assert set(builtin) == {'text-stats', 'weekly-report'}
    assert all(r['source'] == 'builtin' and r['source_tenant_id'] == str(SYSTEM_TENANT_ID) and not r['disabled']
               for r in builtin.values())


def test_a_space_skill_cannot_take_a_builtin_name(database):
    tenant, _ = _tenant(database)
    _make_platform_admin(database)
    with database() as db:
        import_builtin(db, PRINCIPAL, ROOT)
    text = '---\nname: text-stats\ndescription: other\ntools: []\n---\nBody\n'
    with database() as db, pytest.raises(InvalidConfiguration, match='skill_name_taken_by_builtin'):
        publish(db, PRINCIPAL, tenant.id, text, {})


def test_operator_import_reports_failures_per_folder(database, tmp_path):
    folder = tmp_path / 'broken'
    folder.mkdir()
    (folder / 'SKILL.md').write_text('no frontmatter', encoding='utf-8')
    with database() as db:
        results = import_builtin_as(db, SYSTEM_USER_ID, tmp_path)
    assert [(r['folder'], r['status']) for r in results] == [('broken', 'failed')]
