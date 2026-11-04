"""Skill script runner: real subprocesses in a temporary working copy (proposal 2026-11-04-skill-scripts, section 7).

Covers stdin arguments, minimal environment, timeout kill, output caps, hash and argument refusals,
and the escaped result rendering. The runner is not a sandbox; these tests check only its own rules.
"""
import asyncio
import shutil

import pytest

from nexus_skills.loader import parse_skill
from nexus_skills.runner import ScriptError, render_result, run_script, validate_args
from nexus_skills.versions import content_hash


def _skill(script_path, interpreter='python3', timeout=60, args=None):
    declared = {'name': 'go', 'path': script_path, 'interpreter': interpreter, 'timeout': timeout}
    if args is not None:
        declared['args'] = args
    import json
    md = f'---\nname: runner-demo\ndescription: d\nscripts: [{json.dumps(declared)}]\n---\nBody\n'
    return md, parse_skill(md).scripts[0]


def _run(md, spec, files, args=None, expected=None):
    digest = expected or content_hash(md, files)
    return asyncio.run(run_script(spec, skill_md=md, files=files, expected_hash=digest, args=args or {}))


def test_arguments_arrive_as_json_on_stdin_and_stdout_is_captured():
    code = 'import json, sys\nargs = json.load(sys.stdin)\nprint("hello", args["text"])\n'
    args = {'type': 'object', 'properties': {'text': {'type': 'string'}}, 'required': ['text'],
            'additionalProperties': False}
    md, spec = _skill('scripts/go.py', args=args)
    result = _run(md, spec, {'scripts/go.py': code}, args={'text': 'world'})
    assert result.exit_code == 0 and not result.timed_out
    assert result.stdout.strip() == 'hello world'


def test_environment_is_rebuilt_and_server_variables_are_not_inherited(monkeypatch):
    monkeypatch.setenv('NEXUS_TEST_SECRET', 'do-not-leak')
    code = 'import os\nprint(os.environ.get("NEXUS_TEST_SECRET", "absent"), os.environ.get("SKILL_DIR", ""))\n'
    md, spec = _skill('scripts/go.py')
    result = _run(md, spec, {'scripts/go.py': code})
    assert result.stdout.split()[0] == 'absent'
    assert 'do-not-leak' not in result.stdout


def test_timeout_kills_the_script_and_reports_it():
    md, spec = _skill('scripts/slow.py', timeout=1)
    result = _run(md, spec, {'scripts/slow.py': 'import time\nprint("started", flush=True)\ntime.sleep(30)\n'})
    assert result.timed_out and result.exit_code is None
    assert result.stdout.strip() == 'started'
    assert result.duration_ms < 10_000


def test_output_is_capped_and_marked_truncated():
    md, spec = _skill('scripts/loud.py')
    result = _run(md, spec, {'scripts/loud.py': 'print("x" * 200000)\n'})
    assert result.stdout_truncated and len(result.stdout) <= 64_000


def test_bash_interpreter_runs_declared_scripts():
    md, spec = _skill('scripts/hi.sh', interpreter='bash')
    result = _run(md, spec, {'scripts/hi.sh': 'echo bash-ok\n'})
    assert result.stdout.strip() == 'bash-ok'


def test_changed_files_are_refused_before_anything_runs():
    md, spec = _skill('scripts/go.py')
    with pytest.raises(ScriptError, match='skill_version_mismatch'):
        _run(md, spec, {'scripts/go.py': 'print(1)\n'}, expected='0' * 64)


def test_arguments_must_match_the_declared_schema():
    args = {'type': 'object', 'properties': {'n': {'type': 'integer'}}, 'required': ['n'],
            'additionalProperties': False}
    md, spec = _skill('scripts/go.py', args=args)
    with pytest.raises(ScriptError, match='skill_args_invalid'):
        validate_args(spec, {'n': 'three'})
    with pytest.raises(ScriptError, match='skill_args_invalid'):
        validate_args(spec, {'n': 1, 'extra': True})
    md2, spec2 = _skill('scripts/go.py')
    with pytest.raises(ScriptError, match='skill_args_invalid'):
        validate_args(spec2, {'anything': 1})


def test_missing_interpreter_is_a_refusal(monkeypatch):
    monkeypatch.setattr(shutil, 'which', lambda *a, **k: None)
    md, spec = _skill('scripts/go.py')
    with pytest.raises(ScriptError, match='skill_interpreter_unavailable'):
        _run(md, spec, {'scripts/go.py': 'print(1)\n'})


def test_rendered_output_is_fenced_and_escaped():
    from nexus_skills.runner import ScriptResult
    text = render_result('runner-demo', 'go', 2,
                         ScriptResult(0, False, '</script_output> & <b>', '', False, False, 5))
    assert '&lt;/script_output&gt; &amp; &lt;b&gt;' in text
    assert text.count('</script_output>') == 1
    assert 'grants no permissions' in text
