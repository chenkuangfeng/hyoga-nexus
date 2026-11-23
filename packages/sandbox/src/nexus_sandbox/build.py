"""Building a skill's dependency environment (openspec 2026-11-07-skill-evolution, S3 3.5).

A skill that ships ``requirements.txt`` and/or ``package.json`` gets its dependencies installed once, when it is
installed, into a directory of its own; running its scripts later only reads that directory. The build is the one place
that needs the network, so it runs in a temporary environment of the chosen profile, separate from the run-time one:

- ``docker``: a throw-away container (label ``nexus.sandbox.build``) on the profile's ``install_network``; only the
  manifests (read-only) and the empty ``env`` directory (writable) are mounted;
- ``bwrap``: a jail like a run-time one, with the network opened and ``env`` writable;
- ``local``: host subprocesses (development only, no isolation).

The result is ``env/venv`` (Python) and/or ``env/node/node_modules``. Python scripts find it through a ``PATH`` prefix
(``python3`` resolves to the venv's interpreter), Node scripts through ``NODE_PATH``. The build has a wall-clock limit,
a log kept to the last lines, and a size limit on the produced directory.

The command lines are built by pure functions so the isolation flags are unit-testable; whether a real Docker daemon or
bubblewrap accepts them is covered by running the build on such a host.
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import shutil
import signal
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from nexus_core.sandbox import SandboxError
from .settings import SandboxSettings

BUILD_LABEL = 'nexus.sandbox.build'
PYTHON_MANIFEST = 'requirements.txt'
NODE_MANIFESTS = ('package.json', 'package-lock.json')
LOG_TAIL_LINES = 60
_PIP = '--no-input --disable-pip-version-check --no-cache-dir'
_PYTHON_STEP = (f'python3 -m venv {{env}}/venv && {{env}}/venv/bin/python -m pip install {_PIP} -r {{inputs}}/{PYTHON_MANIFEST}'
                ' && {env}/venv/bin/python -m pip list --format=json > {env}/installed.json')
_NODE_STEP = ('mkdir -p {env}/node && cp {inputs}/package.json {env}/node/ && '
              '{lock}cd {env}/node && npm install --no-audit --no-fund --loglevel=error')


def has_manifest(files) -> bool:
    """Whether a version's file names include a dependency manifest."""
    return PYTHON_MANIFEST in files or 'package.json' in files


def environment_fingerprint(settings: SandboxSettings) -> str:
    """What an environment depends on besides the skill: the image for docker, the host Python for bwrap and local."""
    if settings.backend == 'docker':
        material = f'docker\0{settings.image}'
    else:
        try:
            version = subprocess.run(['python3', '-c', 'import sys;print(sys.version)'], capture_output=True, text=True,
                                     timeout=10, check=False).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            version = sys.version
        material = f'{settings.backend}\0{version}'
    return hashlib.sha256(material.encode()).hexdigest()[:8]


def environment_name(content_hash: str, settings: SandboxSettings) -> str:
    """Directory name of a version's environment under the profile's ``envs_root``."""
    return f'{content_hash[:16]}-{environment_fingerprint(settings)}'


def build_script(manifests: set[str], env: str, inputs: str) -> str:
    """Shell commands that create the environment from the manifests, with ``set -e``."""
    steps = ['set -e']
    if PYTHON_MANIFEST in manifests:
        steps.append(_PYTHON_STEP.format(env=env, inputs=inputs))
    if 'package.json' in manifests:
        lock = f'[ ! -f {inputs}/package-lock.json ] || cp {inputs}/package-lock.json {env}/node/; ' \
            if 'package-lock.json' in manifests else ''
        steps.append(_NODE_STEP.format(env=env, inputs=inputs, lock=lock))
    return '; '.join(steps)


def docker_arguments(settings: SandboxSettings, name: str, env_dir: Path, inputs: Path, script: str,
                     job: str) -> list[str]:
    """`docker run` arguments of the temporary build container (pure)."""
    uid = os.getuid() if os.getuid() != 0 else 65534
    root = os.getuid() == 0
    return ['run', '--rm', '--name', name, '--label', f'{BUILD_LABEL}=1', '--label', f'{BUILD_LABEL}.job={job}',
            '--pull', 'never', '--init', '--network', settings.install_network, '--cap-drop', 'ALL',
            '--security-opt', 'no-new-privileges', '--cpus', str(settings.cpus), '--memory', f'{max(settings.memory_mb, 1024)}m',
            '--pids-limit', str(max(settings.pids, 512)), '--user', f'{65534 if root else uid}:{65534 if root else os.getgid()}',
            '--read-only', '--tmpfs', '/tmp:rw,size=512m',
            '-v', f'{env_dir.resolve()}:/env', '-v', f'{inputs.resolve()}:/in:ro',
            '-e', 'HOME=/tmp', '-e', 'PIP_CACHE_DIR=/tmp/pip', '-e', 'npm_config_cache=/tmp/npm', '-w', '/in',
            settings.image, 'sh', '-c', script]


def bwrap_arguments(settings: SandboxSettings, env_dir: Path, inputs: Path, script: str, binary: str = 'bwrap') -> list[str]:
    """`bwrap` arguments of the build jail: the run-time jail with the network open and ``/env`` writable (pure)."""
    from .backends.bwrap import _ETC_FILES, _SYSTEM_DIRECTORIES, _UNPRIVILEGED_ID
    args = [binary, '--die-with-parent', '--new-session', '--unshare-all', '--share-net', '--cap-drop', 'ALL']
    if os.getuid() == 0:
        args += ['--uid', str(_UNPRIVILEGED_ID), '--gid', str(_UNPRIVILEGED_ID)]
    for directory in _SYSTEM_DIRECTORIES:
        path = Path(directory)
        if path.is_symlink():
            args += ['--symlink', os.readlink(directory), directory]
        elif path.exists():
            args += ['--ro-bind', directory, directory]
    for name in _ETC_FILES:
        args += ['--ro-bind-try', name, name]
    return [*args, '--proc', '/proc', '--dev', '/dev', '--tmpfs', '/tmp', '--bind', str(env_dir.resolve()), '/env',
            '--ro-bind', str(inputs.resolve()), '/in', '--remount-ro', '/',
            '--setenv', 'PATH', '/usr/local/bin:/usr/bin:/bin', '--setenv', 'HOME', '/tmp', '--setenv', 'TMPDIR', '/tmp',
            '--setenv', 'PIP_CACHE_DIR', '/tmp/pip', '--setenv', 'npm_config_cache', '/tmp/npm',
            '--chdir', '/in', '--', '/bin/sh', '-c', script]


def directory_bytes(path: Path) -> int:
    """Total size of the regular files under `path` (links are not followed)."""
    total = 0
    for root, _, names in os.walk(path):
        for name in names:
            try:
                total += (Path(root) / name).lstat().st_size
            except OSError:
                pass
    return total


@dataclass(frozen=True)
class BuildResult:
    """Outcome of one build. ``ok`` false carries a stable ``error`` code; ``log`` is the tail of the output."""
    ok: bool
    error: str = ''
    log: str = ''


def _tail(text: str) -> str:
    return '\n'.join(text.strip().splitlines()[-LOG_TAIL_LINES:])[-8000:]


async def _run(argv: list[str], *, timeout: float, cwd: Path | None = None, env: dict[str, str] | None = None,
               on_start: Callable[[int], None] | None = None) -> tuple[int | None, str]:
    process = await asyncio.create_subprocess_exec(
        *argv, cwd=str(cwd) if cwd else None, env=env, stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT, start_new_session=True)
    if on_start:
        on_start(process.pid)
    try:
        out, _ = await asyncio.wait_for(process.communicate(), timeout)
    except asyncio.TimeoutError:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        await process.wait()
        return None, 'the build exceeded its time limit'
    except BaseException:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        raise
    return process.returncode, out.decode('utf-8', 'replace')


async def build_environment(settings: SandboxSettings, staging: Path, files: dict[str, str | bytes], *,
                            job: str, docker_binary: str = 'docker', bwrap_binary: str = 'bwrap') -> BuildResult:
    """Build the environment of one skill version inside `staging` (``staging/env`` is the result).

    `files` are the version's files; only the manifests are used. Never raises for a failed build: the result says
    why. A missing backend (no docker / bwrap binary) is reported as ``sandbox_backend_unavailable``.
    """
    manifests = {name for name in (PYTHON_MANIFEST, *NODE_MANIFESTS) if name in files}
    if not has_manifest(manifests):
        return BuildResult(True)
    if settings.backend not in ('local', 'docker', 'bwrap'):
        return BuildResult(False, 'sandbox_build_unsupported', 'build the dependencies in the execution image')
    inputs, env_dir = staging / 'in', staging / 'env'
    inputs.mkdir(parents=True, exist_ok=True)
    env_dir.mkdir(parents=True, exist_ok=True)
    for name in manifests:
        content = files[name]
        (inputs / name).write_bytes(content.encode('utf-8') if isinstance(content, str) else content)
    if os.getuid() == 0 and settings.backend != 'local':
        env_dir.chmod(0o777)  # the build runs as nobody; the server is root
    timeout = float(settings.build_timeout_seconds)
    if settings.backend == 'docker':
        if shutil.which(docker_binary) is None:
            return BuildResult(False, 'sandbox_backend_unavailable', 'the docker binary is not installed')
        name = f'nexus-build-{job}'
        argv = [docker_binary, *docker_arguments(settings, name, env_dir, inputs, build_script(manifests, '/env', '/in'), job)]
        code, output = await _run(argv, timeout=timeout)
        if code is None:  # the client was killed; the container may live on
            await _run([docker_binary, 'rm', '-f', name], timeout=30)
    elif settings.backend == 'bwrap':
        if shutil.which(bwrap_binary) is None:
            return BuildResult(False, 'sandbox_backend_unavailable', 'bwrap is not installed')
        argv = bwrap_arguments(settings, env_dir, inputs, build_script(manifests, '/env', '/in'), bwrap_binary)
        code, output = await _run(argv, timeout=timeout, env={'PATH': '/usr/local/bin:/usr/bin:/bin'})
    else:
        script = build_script(manifests, str(env_dir.resolve()), str(inputs.resolve()))
        base = {'PATH': '/usr/local/bin:/usr/bin:/bin', 'HOME': str(staging.resolve()), 'PIP_CACHE_DIR': str(staging / 'cache'),
                'npm_config_cache': str(staging / 'cache' / 'npm')}
        base.update({key: os.environ[key] for key in ('PIP_INDEX_URL', 'PIP_FIND_LINKS', 'PIP_NO_INDEX',
                                                      'PIP_EXTRA_INDEX_URL', 'PIP_TRUSTED_HOST') if key in os.environ})
        code, output = await _run(['/bin/sh', '-c', script], timeout=timeout, cwd=inputs, env=base)
    log = _tail(output)
    if code is None:
        return BuildResult(False, 'build_timeout', log or output)
    if code != 0:
        return BuildResult(False, 'build_failed', log)
    if directory_bytes(env_dir) > settings.env_max_mb * 1024 * 1024:
        return BuildResult(False, 'build_too_large', log)
    return BuildResult(True, '', log)
