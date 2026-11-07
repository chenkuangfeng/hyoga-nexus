"""The example skills under skills/general stay valid: they publish, and the script produces its documented output
when run the way `exec_skill` runs it (projected into a sandbox session, text on standard input).

Covers the examples written for proposal 2026-11-04-skill-scripts, task 9.1, as changed by 2026-11-07-skill-evolution.
"""
import asyncio
import json
from pathlib import Path

from nexus_sandbox.manager import SandboxManager
from nexus_sandbox.settings import SandboxSettings
from nexus_skills.exec import build_command, resolve_script
from nexus_skills.loader import parse_skill
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
    assert skill.name == 'text-stats' and skill.scripts == ()  # a script needs no declaration
    assert 'refs/usage.md' in files and 'scripts/count.py' in files


def test_example_skills_publish_through_the_platform_service(database):
    tenant, _ = _tenant(database)
    for name in ('weekly-report', 'text-stats'):
        skill_md, files = _load(name)
        result = _publish(database, tenant, text=skill_md, files=files)
        assert result['version'] == 1 and result['scan_hints'] == []


def test_count_script_reports_characters_words_and_lines(tmp_path):
    skill_md, files = _load('text-stats')
    settings = SandboxSettings(enabled=True, backend='local', allow_local=True, workspace_root=str(tmp_path / 'sbx'))
    session = SandboxManager(settings).session('t1', 's1')
    skill_dir = session.project_skill('text-stats', content_hash(skill_md, files), {'SKILL.md': skill_md, **files})
    script = resolve_script('scripts/count.py', {'SKILL.md': skill_md, **files})
    assert script.interpreter == 'python3'
    command = build_command(script.interpreter, skill_dir, script.path, [])

    def count(text):
        result = asyncio.run(session.exec(command, cwd='/workspace', timeout_seconds=10, stdin=text))
        assert result.exit_code == 0 and not result.timed_out, result.stderr
        return json.loads(result.stdout)

    assert count('a b\nc') == {'characters': 5, 'words': 3, 'lines': 2}
    assert count('一段中文\n') == {'characters': 5, 'words': 1, 'lines': 1}
    assert count('') == {'characters': 0, 'words': 0, 'lines': 0}
    assert count('"quoted" $HOME `x`') == {'characters': 18, 'words': 3, 'lines': 1}  # shell characters are just text
