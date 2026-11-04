"""Publish-time checks for skill content: allowed interpreters, script presence and static hints.

Static hints are advisory. They point at patterns that deserve review (network access, credential
reads, file writes, obfuscation) and are recorded with the version. They never block publishing, and
they are not a security guarantee: a regex cannot tie a dynamic destination to a write.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from ..loader import ParsedSkill

#: Pattern name -> regex. Keep the list short and reviewable; each match is reported with its file and line.
HINT_PATTERNS: dict[str, re.Pattern[str]] = {
    'network': re.compile(r'\b(requests|urllib|httpx|aiohttp|socket|curl|wget)\b|https?://'),
    'credential_read': re.compile(r'os\.environ|getenv\(|API_KEY|SECRET|TOKEN|PASSWORD', re.IGNORECASE),
    'file_write': re.compile(r"open\([^)]*['\"][wa]|write_text\(|write_bytes\(|shutil\.|\brm\s+-rf\b"),
    'obfuscation': re.compile(r'\b(eval|exec)\(|base64\.b64decode|\\x[0-9a-fA-F]{2}'),
}


@dataclass(frozen=True)
class Hint:
    """One advisory finding. ``category`` is a key of :data:`HINT_PATTERNS`."""
    category: str
    path: str
    line: int


def check_declared_scripts(skill: ParsedSkill, files: dict[str, str]) -> list[str]:
    """Return stable error codes for scripts whose file is missing from the version.

    Interpreter whitelisting already happens in :func:`nexus_skills.loader.parse_skill`; this step
    adds the existence check that needs the version's files.
    """
    errors: list[str] = []
    for script in skill.scripts:
        if script.path not in files:
            errors.append(f'skill_script_missing:{script.name}')
    return errors


def static_hints(files: dict[str, str]) -> list[Hint]:
    """Scan script files for advisory patterns. Only ``scripts/`` files are scanned."""
    hints: list[Hint] = []
    for path, text in sorted(files.items()):
        if not path.startswith('scripts/'):
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            for category, pattern in HINT_PATTERNS.items():
                if pattern.search(line):
                    hints.append(Hint(category=category, path=path, line=number))
    return hints
