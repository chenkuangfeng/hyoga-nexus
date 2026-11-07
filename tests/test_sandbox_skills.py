"""Skills inside the sandbox: projection, command environment and standard input
(openspec 2026-11-07-skill-evolution, S2)."""
import asyncio
import os
import stat

import pytest

from nexus_core.sandbox import SandboxError
from nexus_sandbox import skills as projection
from nexus_sandbox.backends.bwrap import BwrapBackend
from nexus_sandbox.backends.docker import DockerBackend
from nexus_sandbox.manager import SandboxManager
from nexus_sandbox.session import MAX_STDIN_BYTES
from nexus_sandbox.settings import SandboxSettings

HASH = 'a' * 64


def run(coro):
    return asyncio.run(coro)


def local_session(tmp_path, **overrides):
    settings = SandboxSettings(enabled=True, backend='local', workspace_root=str(tmp_path / 'sbx'), allow_local=True, **overrides)
    return SandboxManager(settings).session('t1', 's1')


# ------------------------------------------------------------------ projection

def test_a_skill_is_written_once_under_a_content_addressed_name(tmp_path):
    target = projection.project(tmp_path, 'report-writer', HASH, {'SKILL.md': 'x', 'scripts/run.py': 'print(1)', 'refs/a/b.md': 'y'})
    assert target.name == 'report-writer@' + 'a' * 12
    assert (target / 'scripts' / 'run.py').read_text() == 'print(1)' and (target / 'refs' / 'a' / 'b.md').read_text() == 'y'
    assert not os.access(target / 'SKILL.md', os.W_OK) or os.geteuid() == 0  # files are read-only
    assert projection.project(tmp_path, 'report-writer', HASH, {'SKILL.md': 'other'}) == target
    assert (target / 'SKILL.md').read_text() == 'x'  # the same content hash is never overwritten
    assert not [p for p in tmp_path.iterdir() if p.name.startswith('.tmp-')]  # no staging directory is left behind


def test_a_different_hash_is_a_different_directory(tmp_path):
    first = projection.project(tmp_path, 'skill', HASH, {'SKILL.md': '1'})
    second = projection.project(tmp_path, 'skill', 'b' * 64, {'SKILL.md': '2'})
    assert first != second and (first / 'SKILL.md').read_text() == '1' and (second / 'SKILL.md').read_text() == '2'


@pytest.mark.parametrize('name, content_hash', [('', HASH), ('../x', HASH), ('a b', HASH), ('x' * 65, HASH), ('ok', 'short'),
                                                 ('ok', 'XYZ' * 10), ('ok', '../' + 'a' * 20)])
def test_unsafe_names_and_hashes_are_refused(tmp_path, name, content_hash):
    with pytest.raises(SandboxError) as error:
        projection.project(tmp_path, name, content_hash, {'SKILL.md': 'x'})
    assert error.value.code == 'sandbox_skill_invalid'


@pytest.mark.parametrize('path', ['', '/etc/passwd', '../x', 'a/../../x', 'a//b', './a', 'a\\b', 'a\x00b', 'x' * 201])
def test_files_cannot_leave_the_skill_directory(tmp_path, path):
    with pytest.raises(SandboxError) as error:
        projection.project(tmp_path, 'skill', HASH, {'SKILL.md': 'x', path: 'y'})
    assert error.value.code == 'sandbox_skill_invalid'
    assert not [p for p in tmp_path.rglob('*') if p.name == 'y' or p.name.startswith('skill@')]


def test_file_count_and_size_are_bounded(tmp_path, monkeypatch):
    monkeypatch.setattr(projection, 'MAX_FILES', 3)
    with pytest.raises(SandboxError, match='sandbox_skill_too_large'):
        projection.project(tmp_path, 'skill', HASH, {f'f{i}.md': 'x' for i in range(4)})
    monkeypatch.setattr(projection, 'MAX_BYTES', 10)
    with pytest.raises(SandboxError, match='sandbox_skill_too_large'):
        projection.project(tmp_path, 'skill', HASH, {'a.md': 'x' * 11})


def test_binary_files_are_projected_byte_for_byte(tmp_path):
    target = projection.project(tmp_path, 'skill', HASH, {'SKILL.md': 'x', 'assets/blob.bin': bytes(range(256))})
    assert (target / 'assets' / 'blob.bin').read_bytes() == bytes(range(256))


# ------------------------------------------------------------------ the session

def test_the_session_projects_into_the_sessions_own_directory_and_names_the_path_a_command_sees(tmp_path):
    session = local_session(tmp_path)
    directory = session.project_skill('report-writer', HASH, {'SKILL.md': 'body', 'scripts/hello.sh': 'echo hi'})
    assert directory.endswith('/skills/report-writer@' + 'a' * 12)  # on the local profile commands see host paths
    assert directory.startswith(str(tmp_path / 'sbx' / 't1' / 's1'))
    env = session.skill_environment(directory)
    assert env['NEXUS_SKILL_DIR'] == directory and env['NEXUS_SKILL_OUTPUT_DIR'].endswith('/t1/s1/outputs')
    result = run(session.exec('sh "$NEXUS_SKILL_DIR/scripts/hello.sh"', cwd='/workspace', timeout_seconds=5, env=env))
    assert (result.exit_code, result.stdout.strip()) == (0, 'hi')


def test_the_containers_see_projected_skills_at_slash_skills(tmp_path):
    for backend in ('docker', 'bwrap'):
        settings = SandboxSettings(enabled=True, backend=backend, workspace_root=str(tmp_path / backend))
        session = SandboxManager(settings).session('t1', 's1')
        assert session.project_skill('s', HASH, {'SKILL.md': 'x'}) == '/skills/s@' + 'a' * 12
        assert session.skill_environment('/skills/s@x')['NEXUS_SKILL_OUTPUT_DIR'] == '/outputs'


def test_standard_input_reaches_the_command_and_its_size_is_bounded(tmp_path):
    session = local_session(tmp_path)
    result = run(session.exec('cat', cwd='/workspace', timeout_seconds=5, stdin='line one\n"quoted" $HOME\n'))
    assert result.stdout == 'line one\n"quoted" $HOME\n'  # quotes, newlines and shell characters are kept exactly
    assert run(session.exec('cat', cwd='/workspace', timeout_seconds=5, stdin='')).stdout == ''
    assert run(session.exec('echo ${X:-unset}', cwd='/workspace', timeout_seconds=5)).stdout.strip() == 'unset'  # no stdin: closed
    with pytest.raises(SandboxError, match='sandbox_stdin_too_large'):
        run(session.exec('cat', cwd='/workspace', timeout_seconds=5, stdin='x' * (MAX_STDIN_BYTES + 1)))
    big = run(session.exec('wc -c', cwd='/workspace', timeout_seconds=5, stdin='é' * (MAX_STDIN_BYTES // 2)))
    assert big.stdout.strip() == str(MAX_STDIN_BYTES)  # the limit counts bytes, not characters


def test_a_command_that_ignores_its_input_does_not_hang_or_fail(tmp_path):
    session = local_session(tmp_path)
    result = run(session.exec('echo done', cwd='/workspace', timeout_seconds=5, stdin='x' * 60_000))
    assert (result.exit_code, result.stdout.strip()) == (0, 'done')


@pytest.mark.parametrize('env', [{'lower': 'x'}, {'BAD-NAME': 'x'}, {'1X': 'x'}, {'OK': 'a\x00b'}, {'OK': 'x' * 5000}])
def test_only_wellformed_environment_variables_are_passed(tmp_path, env):
    with pytest.raises(SandboxError, match='sandbox_env_invalid'):
        run(local_session(tmp_path).exec('true', cwd='/workspace', timeout_seconds=5, env=env))


def test_projection_without_a_skills_directory_is_refused(tmp_path):
    session = local_session(tmp_path)
    session.skills_dir = None
    with pytest.raises(SandboxError, match='sandbox_skills_unavailable'):
        session.project_skill('s', HASH, {'SKILL.md': 'x'})


# ------------------------------------------------------------------ backend arguments

def test_docker_mounts_skills_read_only_and_passes_environment_and_input(tmp_path):
    backend = DockerBackend(SandboxSettings(enabled=True, backend='docker'))
    args = backend.run_arguments('n', tmp_path / 'w', tmp_path / 'o', tmp_path / 's')
    assert f'{(tmp_path / "s").resolve()}:/skills:ro' in args
    plain = backend.exec_arguments('n', 'true', '/workspace', 5, 'tok')
    assert '-i' not in plain and '-e' not in plain
    full = backend.exec_arguments('n', 'true', '/workspace', 5, 'tok', {'NEXUS_SKILL_DIR': '/skills/s@abc'}, True)
    assert full[:3] == ['exec', '-i', '-w'] and ['-e', 'NEXUS_SKILL_DIR=/skills/s@abc'] == full[full.index('-e'):full.index('-e') + 2]
    assert full.index('n') > full.index('-e')  # options come before the container name


def test_bwrap_binds_skills_read_only_and_sets_the_environment(tmp_path):
    backend = BwrapBackend(SandboxSettings(enabled=True, backend='bwrap'))
    skills = tmp_path / 's'
    skills.mkdir()
    args = backend.jail_arguments(tmp_path / 'w', tmp_path / 'o', '/workspace', 'true', {'NEXUS_SKILL_DIR': '/skills/x'}, skills)
    at = args.index(str(skills.resolve()))
    assert args[at - 1:at + 2] == ['--ro-bind', str(skills.resolve()), '/skills']
    assert args[args.index('NEXUS_SKILL_DIR') - 1] == '--setenv' and args[args.index('NEXUS_SKILL_DIR') + 1] == '/skills/x'
    without = backend.jail_arguments(tmp_path / 'w', tmp_path / 'o', '/workspace', 'true')
    assert '/skills' not in without
