"""Immutable skill version content: size limits, file path rules and content hashing.

A published SkillVersion is identified by :func:`content_hash`, computed over the SKILL.md text and
every resource file in canonical order. Two versions with the same hash have the same content, so
the hash is what a run checks before it reads or executes anything from a version.
"""
from __future__ import annotations

import hashlib
import json
import posixpath
from collections.abc import Mapping

MAX_FILES = 100
MAX_FILE_CHARS = 64_000
MAX_TOTAL_CHARS = 512_000
MAX_SKILL_MD_CHARS = 64_000
MAX_PATH_LENGTH = 200


class SkillFileError(ValueError):
    """A resource path or size breaks the version rules; the message is a stable code."""


def normalize_path(path: str) -> str:
    """Return the canonical relative POSIX path, or raise when it could escape the skill directory.

    Rejected: empty paths, absolute paths, backslashes, NUL bytes, ``..`` segments after
    normalization, and paths longer than :data:`MAX_PATH_LENGTH`.
    """
    if not isinstance(path, str) or not path or len(path) > MAX_PATH_LENGTH:
        raise SkillFileError('skill_path_invalid')
    if path.startswith('/') or '\\' in path or '\x00' in path:
        raise SkillFileError('skill_path_invalid')
    normalized = posixpath.normpath(path)
    if normalized in ('.', '') or normalized.startswith('../') or normalized == '..':
        raise SkillFileError('skill_path_invalid')
    return normalized


def check_files(files: Mapping[str, str]) -> dict[str, str]:
    """Validate resource files and return them keyed by canonical path.

    Two input paths that normalize to the same file are rejected, so the version cannot contain
    ambiguous duplicates.
    """
    if len(files) > MAX_FILES:
        raise SkillFileError('skill_too_many_files')
    checked: dict[str, str] = {}
    total = 0
    for raw_path, content in files.items():
        path = normalize_path(raw_path)
        if path in checked:
            raise SkillFileError('skill_path_duplicate')
        if not isinstance(content, str) or len(content) > MAX_FILE_CHARS:
            raise SkillFileError('skill_file_too_large')
        total += len(content)
        if total > MAX_TOTAL_CHARS:
            raise SkillFileError('skill_total_too_large')
        checked[path] = content
    return dict(sorted(checked.items()))


def content_hash(skill_md: str, files: Mapping[str, str]) -> str:
    """SHA-256 over the canonical JSON of SKILL.md and the resource files (sorted by path)."""
    if len(skill_md) > MAX_SKILL_MD_CHARS:
        raise SkillFileError('skill_md_too_large')
    payload = json.dumps({'skill.md': skill_md, 'files': dict(sorted(files.items()))},
                         ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()
