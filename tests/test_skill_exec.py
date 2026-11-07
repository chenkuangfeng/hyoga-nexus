"""Pure rules for running a skill script: file, interpreter, command line, arguments and where a skill may run
(openspec 2026-11-07-skill-evolution, S2)."""
import hashlib
import shlex

import pytest

from nexus_skills.exec import MAX_ARGS, MAX_ARG_CHARS, ScriptError, build_command, check_args, resolve_script
from nexus_skills.policy import resolve_execution

FILES = {
    'SKILL.md': '# doc', 'scripts/run.py': 'print(1)', 'scripts/go.sh': 'echo', 'scripts/app.mjs': '1', 'tools/convert': '#!/usr/bin/env python3\nprint(1)',
    'tools/sh': '#!/bin/sh\necho', 'tools/node': '#!/usr/bin/env -S node --flag\n1', 'tools/perl': '#!/usr/bin/perl\n1', 'tools/plain': 'just text',
    'refs/data.json': '{}', 'scripts/UPPER.PY': 'x', 'scripts/binary.py': b'\x00\x01',
}


@pytest.mark.parametrize('path, interpreter', [
    ('scripts/run.py', 'python3'), ('scripts/go.sh', 'bash'), ('scripts/app.mjs', 'node'), ('scripts/UPPER.PY', 'python3'),
    ('tools/convert', 'python3'), ('tools/sh', 'sh'), ('tools/node', 'node'),
])
def test_the_interpreter_comes_from_the_extension_or_the_shebang(path, interpreter):
    resolved = resolve_script(path, FILES)
    assert (resolved.path, resolved.interpreter) == (path, interpreter)


def test_a_path_is_canonicalized_before_it_is_looked_up():
    assert resolve_script('scripts//run.py', FILES).path == 'scripts/run.py'
    assert resolve_script('./scripts/run.py', FILES).path == 'scripts/run.py'


def test_the_hash_is_that_of_the_file_content():
    assert resolve_script('scripts/run.py', FILES).content_hash == hashlib.sha256(b'print(1)').hexdigest()
    assert resolve_script('scripts/binary.py', FILES).content_hash == hashlib.sha256(b'\x00\x01').hexdigest()


@pytest.mark.parametrize('script', ['', '../etc/passwd', '/etc/passwd', 'scripts/../../x', 'scripts\\run.py',
                                    'scripts/missing.py', 'scripts', 'x' * 300])
def test_a_path_outside_the_version_or_a_missing_file_is_unavailable(script):
    with pytest.raises(ScriptError, match='skill_script_unavailable'):
        resolve_script(script, FILES)


@pytest.mark.parametrize('script', ['SKILL.md', 'refs/data.json', 'tools/perl', 'tools/plain'])
def test_an_unlisted_interpreter_is_refused(script):
    with pytest.raises(ScriptError, match='skill_script_interpreter_not_allowed'):
        resolve_script(script, FILES)


@pytest.mark.parametrize('args', [['a', 'b c', ';', '$(id)', '`id`', '*', '"q"', "it's", '--flag=x y', '', '\n'], []])
def test_every_argument_reaches_the_script_as_one_plain_word(args):
    command = build_command('python3', '/skills/s@abc', 'scripts/run.py', args)
    assert shlex.split(command) == ['python3', '/skills/s@abc/scripts/run.py', *args]  # what `sh -c` makes of it


def test_the_skill_directory_is_quoted_too():
    command = build_command('bash', '/skills/odd name;x@abc/', 'scripts/go.sh', [])
    assert shlex.split(command) == ['bash', '/skills/odd name;x@abc/scripts/go.sh']


@pytest.mark.parametrize('bad', ['text', {'a': 1}, [1], [None], ['a\x00b'], ['x' * (MAX_ARG_CHARS + 1)], ['a'] * (MAX_ARGS + 1)])
def test_arguments_are_a_bounded_list_of_strings(bad):
    with pytest.raises(ScriptError, match='skill_script_args_invalid'):
        check_args(bad)


def test_valid_arguments_pass_through():
    assert check_args(None) == [] and check_args([]) == [] and check_args(['a', 'b']) == ['a', 'b']
    assert len(check_args(['x'] * MAX_ARGS)) == MAX_ARGS


# ------------------------------------------------------------------ where a skill may run

@pytest.mark.parametrize('declared, source, profile, accepted, local_scripts, expected', [
    ('sandbox', 'admin', 'docker', True, False, (True, '')),
    ('sandbox', 'import', 'bwrap', True, False, (True, '')),
    ('sandbox', 'admin', 'docker', False, False, (False, 'sandbox_unavailable')),     # no fallback to the host
    ('sandbox', 'admin', 'local', True, False, (True, '')),                           # a usable local profile (development mode)
    ('sandbox', 'admin', 'local', False, False, (False, 'sandbox_unavailable')),
    ('local', 'builtin', 'local', True, True, (True, '')),
    ('local', 'builtin', 'local', True, False, (False, 'local_not_allowed')),         # deployment switch off
    ('local', 'builtin', 'local', False, True, (False, 'local_not_allowed')),         # profile not usable
    ('local', 'builtin', 'docker', True, True, (False, 'local_not_allowed')),         # no fallback to a sandbox either
    ('local', 'admin', 'local', True, True, (False, 'skill_execution_not_permitted')),
    ('local', 'import', 'local', True, True, (False, 'skill_execution_not_permitted')),
    ('local', 'user', 'local', True, True, (False, 'skill_execution_not_permitted')),
])
def test_where_a_skills_scripts_may_run(declared, source, profile, accepted, local_scripts, expected):
    assert resolve_execution(declared, source, profile_type=profile, accepted=accepted, allow_local_scripts=local_scripts) == expected
