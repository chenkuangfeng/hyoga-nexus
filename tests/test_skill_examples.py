"""The example skills under skills/general stay valid: they publish, and the script produces its documented output.

Covers the examples written for proposal 2026-11-04-skill-scripts, task 9.1.
"""
import asyncio
import json
from pathlib import Path

from nexus_skills.loader import parse_skill
from nexus_skills.runner import run_script
from nexus_skills.versions import content_hash
from test_platform import database  # noqa: F401  (pytest fixture)
from test_skills_platform import _publish, _tenant

ROOT = Path(__file__).resolve().parent.parent / 'skills' / 'general'


def _load(name):
    folder = ROOT / name
    skill_md = (folder / 'SKILL.md').read_text(encoding='utf-8')
    files = {str(path.relative_to(folder)): path.read_text(encoding='utf-8')
             for path in folder.rglob('*') if path.is_file() and path.name != 'SKILL.md'}
    return skill_md, files


def test_example_skills_parse_with_their_declared_dependencies():
    weekly, _ = _load('weekly-report')
    stats, files = _load('text-stats')
    assert parse_skill(weekly).tools == ('read_memory', 'search_memory')
    skill = parse_skill(stats)
    assert skill.name == 'text-stats' and skill.scripts[0].name == 'count'
    assert 'refs/usage.md' in files and 'scripts/count.py' in files


def test_example_skills_publish_through_the_platform_service(database):
    tenant, _ = _tenant(database)
    for name in ('weekly-report', 'text-stats'):
        skill_md, files = _load(name)
        result = _publish(database, tenant, text=skill_md, files=files)
        assert result['version'] == 1 and result['scan_hints'] == []


def test_count_script_reports_characters_words_and_lines():
    skill_md, files = _load('text-stats')
    spec = parse_skill(skill_md).scripts[0]
    digest = content_hash(skill_md, files)

    def count(text):
        result = asyncio.run(run_script(spec, skill_md=skill_md, files=files, expected_hash=digest,
                                        args={'text': text}))
        assert result.exit_code == 0 and not result.timed_out, result.stderr
        return json.loads(result.stdout)

    assert count('a b\nc') == {'characters': 5, 'words': 3, 'lines': 2}
    assert count('一段中文\n') == {'characters': 5, 'words': 1, 'lines': 1}
    assert count('') == {'characters': 0, 'words': 0, 'lines': 0}
