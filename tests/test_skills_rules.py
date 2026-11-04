"""Pure rules for skills (proposal 2026-11-04-skill-scripts, tasks 2.x, 3.2–3.3, 8.x).

No database or subprocess: parsing, path and size limits, hashing and advisory hints.
"""
import pytest

from nexus_skills.guard import check_declared_scripts, static_hints
from nexus_skills.loader import parse_skill
from nexus_skills.loader.frontmatter import SkillFormatError
from nexus_skills.versions import SkillFileError, check_files, content_hash, normalize_path

GOOD = '---\nname: report-writer\ndescription: "Writes weekly reports"\ntools: ["read_memory"]\n---\n# Steps\nDo it.\n'


def _md(extra='', name='report-writer', description='Writes reports'):
    return f'---\nname: {name}\ndescription: {description}\n{extra}---\nBody\n'


def test_valid_skill_is_parsed_with_body_and_tools():
    skill = parse_skill(GOOD)
    assert skill.name == 'report-writer'
    assert skill.description == 'Writes weekly reports'
    assert skill.tools == ('read_memory',)
    assert skill.body == '# Steps\nDo it.'


def test_missing_or_unterminated_frontmatter_is_rejected():
    with pytest.raises(SkillFormatError, match='frontmatter_missing'):
        parse_skill('# no frontmatter')
    with pytest.raises(SkillFormatError, match='frontmatter_unterminated'):
        parse_skill('---\nname: a\ndescription: b\n')


def test_unknown_or_duplicate_keys_are_rejected_not_ignored():
    with pytest.raises(SkillFormatError, match='frontmatter_key_unknown:licence'):
        parse_skill(_md('licence: MIT\n'))
    with pytest.raises(SkillFormatError, match='frontmatter_key_duplicate:name'):
        parse_skill('---\nname: a\nname: b\ndescription: d\n---\n')


@pytest.mark.parametrize('name', ['', 'has space', 'slash/name', 'x' * 65, 'my-Claude-helper', 'anthropic-tools'])
def test_invalid_or_reserved_names_are_rejected(name):
    with pytest.raises(SkillFormatError):
        parse_skill(_md(name=name))


def test_description_limit_is_enforced():
    with pytest.raises(SkillFormatError, match='skill_description_too_long'):
        parse_skill(_md(description='d' * 1025))


def test_tools_must_be_unique_tool_names():
    with pytest.raises(SkillFormatError, match='skill_tools_invalid'):
        parse_skill(_md('tools: ["read_memory", "read_memory"]\n'))
    with pytest.raises(SkillFormatError, match='skill_tools_invalid'):
        parse_skill(_md('tools: ["Bad Name"]\n'))


def test_script_declaration_accepts_only_whitelisted_interpreters_and_scripts_dir():
    ok = parse_skill(_md('scripts: [{"name": "run", "path": "scripts/run.py", "interpreter": "python3"}]\n'))
    assert ok.scripts[0].timeout == 60 and ok.scripts[0].risk_level == 'high'
    with pytest.raises(SkillFormatError, match='skill_script_interpreter_not_allowed'):
        parse_skill(_md('scripts: [{"name": "run", "path": "scripts/run.sh", "interpreter": "sh"}]\n'))
    with pytest.raises(SkillFormatError, match='skill_script_path_invalid'):
        parse_skill(_md('scripts: [{"name": "run", "path": "../run.py", "interpreter": "python3"}]\n'))
    with pytest.raises(SkillFormatError, match='skill_script_path_invalid'):
        parse_skill(_md('scripts: [{"name": "run", "path": "scripts/../../x.py", "interpreter": "python3"}]\n'))


def test_script_timeout_and_risk_are_bounded():
    with pytest.raises(SkillFormatError, match='skill_script_timeout_invalid'):
        parse_skill(_md('scripts: [{"name": "r", "path": "scripts/r.py", "interpreter": "bash", "timeout": 301}]\n'))
    with pytest.raises(SkillFormatError, match='skill_script_risk_invalid'):
        parse_skill(_md('scripts: [{"name": "r", "path": "scripts/r.py", "interpreter": "bash", "risk_level": "low"}]\n'))


@pytest.mark.parametrize('path', ['/etc/passwd', 'a\\b', 'a/../../b', '', 'a\x00b'])
def test_unsafe_resource_paths_are_rejected(path):
    with pytest.raises(SkillFileError, match='skill_path_invalid'):
        normalize_path(path)


def test_resource_paths_are_normalized_and_duplicates_rejected():
    assert normalize_path('refs//a/../b.md') == 'refs/b.md'
    with pytest.raises(SkillFileError, match='skill_path_duplicate'):
        check_files({'refs/a.md': 'x', 'refs/./a.md': 'y'})


def test_file_count_and_size_limits():
    with pytest.raises(SkillFileError, match='skill_file_too_large'):
        check_files({'a.md': 'x' * 64_001})
    with pytest.raises(SkillFileError, match='skill_total_too_large'):
        check_files({f'f{i}.md': 'x' * 64_000 for i in range(9)})
    with pytest.raises(SkillFileError, match='skill_too_many_files'):
        check_files({f'f{i}.md': '' for i in range(101)})


def test_content_hash_is_stable_and_sensitive_to_every_part():
    files = {'refs/a.md': 'one', 'scripts/s.py': 'print(1)'}
    first = content_hash(GOOD, files)
    assert first == content_hash(GOOD, dict(reversed(list(files.items()))))
    assert first != content_hash(GOOD + ' ', files)
    assert first != content_hash(GOOD, {**files, 'refs/a.md': 'two'})


def test_declared_scripts_must_exist_in_the_version():
    skill = parse_skill(_md('scripts: [{"name": "run", "path": "scripts/run.py", "interpreter": "python3"}]\n'))
    assert check_declared_scripts(skill, {}) == ['skill_script_missing:run']
    assert check_declared_scripts(skill, {'scripts/run.py': ''}) == []


def test_static_hints_are_advisory_and_report_file_and_line():
    hints = static_hints({'scripts/run.py': 'x = 1\nimport requests\nopen("out", "w")\n',
                          'refs/notes.md': 'import requests'})
    assert [(h.category, h.path, h.line) for h in hints] == [('network', 'scripts/run.py', 2),
                                                           ('file_write', 'scripts/run.py', 3)]
