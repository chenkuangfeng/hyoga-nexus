"""Projection of skills into a session's sandbox (openspec 2026-11-07-skill-evolution, S2).

A skill is stored in the database; to run one of its scripts, its files are written to the session's ``skills``
directory under a content-addressed name, ``<skill>@<first 12 hex of the content hash>``. The directory is mounted
read-only into the sandbox (``/skills`` for docker and bwrap; the host path for the ``local`` profile, whose commands
see host paths), so a command can read the skill but not change it, and a changed skill never overwrites the
copy a running script is using. Only skills the Run may use are projected, one at a time and on first use; other
sessions, other spaces and unbound skills are never in the directory. The host never executes anything it wrote.
"""
from __future__ import annotations

import os
import re
import shutil
import uuid
from pathlib import Path

from nexus_core.sandbox import SandboxError

#: Limits of one projected skill (the figures WeKnora uses when it stages a skill into a session).
MAX_FILES = 1000
MAX_BYTES = 32 * 1024 * 1024
_NAME = re.compile(r'^[\w-]{1,64}$')
_HASH = re.compile(r'^[0-9a-f]{12,64}$')


def directory_name(name: str, content_hash: str) -> str:
    """Name of a skill's projected directory; raises `sandbox_skill_invalid` for a name or hash that is not safe."""
    if not _NAME.match(name) or not _HASH.match(content_hash):
        raise SandboxError('sandbox_skill_invalid')
    return f'{name}@{content_hash[:12]}'


def _safe_relative(path: str) -> str:
    parts = path.split('/')
    if (not path or path.startswith('/') or '\\' in path or '\x00' in path or len(path) > 200
            or any(part in ('', '.', '..') for part in parts)):
        raise SandboxError('sandbox_skill_invalid')
    return path


def project(skills_dir: Path, name: str, content_hash: str, files: dict[str, str | bytes]) -> Path:
    """Write the skill's files under `skills_dir` and return the directory; reuse it when it already exists.

    `files` maps a relative path (``SKILL.md``, ``scripts/run.py`` ...) to its content. Writing goes to a staging
    directory first and is renamed into place, so a reader never sees a half-written skill and two sessions racing
    to project the same skill both end with a complete copy.
    """
    target = skills_dir / directory_name(name, content_hash)
    if target.is_dir():
        return target
    if len(files) > MAX_FILES:
        raise SandboxError('sandbox_skill_too_large')
    prepared: list[tuple[str, bytes]] = []
    total = 0
    for path, content in files.items():
        data = content.encode('utf-8') if isinstance(content, str) else content
        total += len(data)
        if total > MAX_BYTES:
            raise SandboxError('sandbox_skill_too_large')
        prepared.append((_safe_relative(path), data))
    skills_dir.mkdir(parents=True, exist_ok=True)
    staging = skills_dir / f'.tmp-{uuid.uuid4().hex}'
    try:
        for path, data in prepared:
            destination = staging.joinpath(*path.split('/'))
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)
            destination.chmod(0o444)
        staging.mkdir(parents=True, exist_ok=True)
        for directory in [staging, *[p for p in staging.rglob('*') if p.is_dir()]]:
            directory.chmod(0o755)
        try:
            os.rename(staging, target)
        except OSError:
            if not target.is_dir():  # not a lost race: the rename really failed
                raise SandboxError('sandbox_skill_projection_failed') from None
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return target


def sync_draft(skills_dir: Path, name: str, files: dict[str, str] | None) -> None:
    """Mirror one database-owned private draft beneath the user's persistent skills workspace.

    The database remains authoritative. Each file is replaced atomically, paths use the same strict allowlist as
    private skill drafts, and stale files are removed only from this draft directory.
    """
    from nexus_skills.loader import parse_skill
    if not _NAME.fullmatch(name):
        raise SandboxError('sandbox_skill_invalid')
    base = skills_dir / 'drafts'
    base.mkdir(parents=True, exist_ok=True)
    target = base / name
    if target.is_symlink():
        raise SandboxError('sandbox_skill_invalid')
    if files is None:
        shutil.rmtree(target, ignore_errors=True)
        return
    if 'SKILL.md' not in files or len(files) > MAX_FILES:
        raise SandboxError('sandbox_skill_invalid')
    if parse_skill(files['SKILL.md']).name != name:
        raise SandboxError('sandbox_skill_invalid')
    prepared: dict[str, bytes] = {}
    total = 0
    for path, content in files.items():
        clean = _safe_relative(path)
        if clean != 'SKILL.md' and not clean.startswith(('refs/', 'scripts/', 'assets/', 'templates/')):
            raise SandboxError('sandbox_skill_invalid')
        data = content.encode('utf-8')
        total += len(data)
        if total > MAX_BYTES:
            raise SandboxError('sandbox_skill_too_large')
        prepared[clean] = data
    target.mkdir(parents=True, exist_ok=True)
    existing = {path.relative_to(target).as_posix() for path in target.rglob('*') if path.is_file() and not path.is_symlink()}
    for stale in existing - prepared.keys():
        (target / stale).unlink(missing_ok=True)
    for path, data in prepared.items():
        destination = target.joinpath(*path.split('/'))
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name('.draft-' + uuid.uuid4().hex)
        try:
            temporary.write_bytes(data)
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
