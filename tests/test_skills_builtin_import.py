"""Builtin skill import from the repository's skills/ directory (proposal 2026-11-04-skill-scripts, task 3.4).

Imported skills get the builtin source, so an installed skill with the same name cannot replace them,
and running the import again reports unchanged folders instead of failing.
"""
from pathlib import Path

from nexus_platform.skills.service import import_builtin, publish
from nexus_platform.errors import InvalidConfiguration
from test_platform import database  # noqa: F401  (pytest fixture)
from test_skills_platform import PRINCIPAL, _tenant

ROOT = Path(__file__).resolve().parent.parent / 'skills' / 'general'


def test_import_publishes_example_skills_with_builtin_source_and_is_repeatable(database):
    tenant, _ = _tenant(database)
    with database() as db:
        first = import_builtin(db, PRINCIPAL, tenant.id, ROOT)
        db.commit()
    assert sorted(r['folder'] for r in first) == ['text-stats', 'weekly-report']
    assert all(r['status'] == 'published' and r['version'] == 1 for r in first)
    with database() as db:
        second = import_builtin(db, PRINCIPAL, tenant.id, ROOT)
        db.commit()
    assert all(r['status'] == 'unchanged' for r in second)


def test_installed_skill_cannot_take_a_builtin_name(database):
    tenant, _ = _tenant(database)
    text = '---\nname: text-stats\ndescription: other\ntools: []\n---\nBody\n'
    with database() as db:
        publish(db, PRINCIPAL, tenant.id, text, {})
        db.commit()
    with database() as db:
        results = import_builtin(db, PRINCIPAL, tenant.id, ROOT)
        db.commit()
    by_folder = {r['folder']: r for r in results}
    assert by_folder['text-stats']['status'] == 'failed'
    assert 'skill_source_conflict' in by_folder['text-stats']['error']
    assert by_folder['weekly-report']['status'] == 'published'
