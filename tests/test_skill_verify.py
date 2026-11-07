"""Verification gate (S3 3.6): syntax problems stop an install, missing interpreters only leave a note."""
import shutil

import pytest

from nexus_skills import verify


def _levels(findings):
    return sorted((f.level, f.path) for f in findings)


def test_valid_sources_pass():
    files = {'SKILL.md': 'x', 'scripts/a.py': 'print(1)\n', 'scripts/b.sh': 'echo hi\n'}
    assert [f for f in verify.verify_files(files) if f.level == 'problem'] == []


def test_python_syntax_error_is_a_problem_with_a_line():
    found = verify.verify_files({'scripts/a.py': 'def f(:\n  pass\n'})
    assert _levels(found) == [('problem', 'scripts/a.py')] and 'line 1' in found[0].message


def test_unresolvable_imports_are_not_guessed():
    assert verify.verify_files({'scripts/a.py': 'import definitely_not_installed_pkg\n'}) == []


@pytest.mark.skipif(shutil.which('sh') is None, reason='sh missing')
def test_shell_syntax_error_is_a_problem():
    assert _levels(verify.verify_files({'scripts/a.sh': 'if then\n'})) == [('problem', 'scripts/a.sh')]


@pytest.mark.skipif(shutil.which('node') is None, reason='node missing')
def test_javascript_syntax_error_is_a_problem():
    assert _levels(verify.verify_files({'scripts/a.js': 'function (\n'})) == [('problem', 'scripts/a.js')]


def test_a_missing_interpreter_is_a_note_not_a_failure(monkeypatch):
    monkeypatch.setattr(verify.shutil, 'which', lambda name: None)
    found = verify.verify_files({'scripts/a.js': 'function (\n', 'scripts/b.js': 'x'})
    assert _levels(found) == [('note', 'scripts/a.js')]  # one note per interpreter


def test_requirements_parse_and_reject_indirection():
    names, bad = verify.parse_requirements('# c\nRequests>=2\nPillow[extra]==10 ; python_version>"3"\n\n-r other.txt\n'
                                           'pkg @ https://x/y.whl\n--index-url http://evil\n')
    assert names == ['requests', 'pillow'] and len(bad) == 3
    found = verify.verify_files({'requirements.txt': '-e .\n'})
    assert _levels(found) == [('problem', 'requirements.txt')]


def test_missing_distributions_compare_normalized_names():
    assert verify.missing_distributions(['my-pkg', 'other'], {'My_Pkg'}) == ['other']
