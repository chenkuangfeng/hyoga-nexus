"""Verification gate for a skill about to be installed (openspec 2026-11-07-skill-evolution, S3 3.6).

Deterministic and conservative, after WeKnora's ``tenant_skill_verify``: a ``problem`` stops the install, a ``note``
is kept for the author. Nothing here runs skill code. Syntax checks only:

- ``.py``: ``ast.parse`` (no import is resolved: guessing whether an ``import`` will resolve rejected runnable
  skills in WeKnora, so it is not done);
- ``.sh`` / ``.bash``: ``sh -n`` / ``bash -n`` (parse without executing);
- ``.js`` / ``.mjs`` / ``.cjs``: ``node --check``;
- an interpreter that is not installed on this host only yields a ``note``: the check is skipped, not failed;
- the dependency manifest (``requirements.txt``) must be well formed; whether its packages ended up installed is
  checked by :func:`missing_distributions` against what the build environment reports.
"""
from __future__ import annotations

import ast
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

_TIMEOUT = 10
_REQUIREMENT = re.compile(r'^([A-Za-z0-9][A-Za-z0-9._-]*)\s*(\[[^\]]*\])?\s*((==|>=|<=|~=|!=|<|>|===)[^;#]*)?(;.*)?$')
_NAME_PUNCT = re.compile(r'[-_.]+')


@dataclass(frozen=True)
class Finding:
    """One result. ``level`` is ``problem`` (stops the install) or ``note``."""
    level: str
    path: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {'level': self.level, 'path': self.path, 'message': self.message}


def _syntax_command(path: str) -> tuple[str, list[str]] | None:
    lower = path.lower()
    if lower.endswith('.sh'):
        return 'sh', ['sh', '-n']
    if lower.endswith('.bash'):
        return 'bash', ['bash', '-n']
    if lower.endswith(('.js', '.mjs', '.cjs')):
        return 'node', ['node', '--check']
    return None


def normalize_distribution(name: str) -> str:
    """PEP 503 name normalisation, so ``Pillow`` / ``pillow`` and ``a_b`` / ``a-b`` compare equal."""
    return _NAME_PUNCT.sub('-', name).lower()


def parse_requirements(text: str) -> tuple[list[str], list[str]]:
    """(normalized distribution names, malformed lines) of a ``requirements.txt``.

    Comments and blank lines are skipped. Options (``-r``, ``-e``, ``--index-url``) and direct URLs are reported as
    malformed: an install must not reach a different index or a local path chosen by the skill author.
    """
    names: list[str] = []
    bad: list[str] = []
    for raw in text.splitlines():
        line = raw.split(' #', 1)[0].strip()
        if not line or line.startswith('#'):
            continue
        match = _REQUIREMENT.match(line)
        if match is None or '@' in line or '://' in line:
            bad.append(line[:80])
            continue
        names.append(normalize_distribution(match.group(1)))
    return names, bad


def missing_distributions(required: list[str], installed: set[str]) -> list[str]:
    """Required distributions the build environment does not report (both sides normalized)."""
    have = {normalize_distribution(name) for name in installed}
    return [name for name in required if normalize_distribution(name) not in have]


def verify_files(files: dict[str, str]) -> list[Finding]:
    """Check every source file of a version (``files`` includes SKILL.md; binary files are not passed in)."""
    findings: list[Finding] = []
    pending: list[tuple[str, str, list[str]]] = []
    for path, content in sorted(files.items()):
        if path.lower().endswith('.py'):
            try:
                ast.parse(content, filename=path)
            except SyntaxError as exc:
                findings.append(Finding('problem', path, f'python_syntax_error:line {exc.lineno}: {exc.msg}'))
            except ValueError as exc:  # e.g. NUL bytes
                findings.append(Finding('problem', path, f'python_unreadable:{exc}'))
            continue
        command = _syntax_command(path)
        if command is not None:
            pending.append((path, content, command[1]))
        if path == 'requirements.txt':
            _, bad = parse_requirements(content)
            findings.extend(Finding('problem', path, f'requirement_unsupported:{line}') for line in bad)
    skipped: set[str] = set()
    if pending:
        with tempfile.TemporaryDirectory(prefix='nexus-verify-') as scratch:
            for index, (path, content, argv) in enumerate(pending):
                if shutil.which(argv[0]) is None:
                    if argv[0] not in skipped:
                        skipped.add(argv[0])
                        findings.append(Finding('note', path, f'interpreter_missing:{argv[0]}; syntax not checked'))
                    continue
                target = Path(scratch) / f'f{index}{Path(path).suffix}'
                target.write_text(content, encoding='utf-8')
                try:
                    done = subprocess.run([*argv, str(target)], capture_output=True, text=True, timeout=_TIMEOUT,
                                          stdin=subprocess.DEVNULL, check=False)
                except subprocess.TimeoutExpired:
                    findings.append(Finding('note', path, 'syntax_check_timeout'))
                    continue
                if done.returncode != 0:
                    detail = (done.stderr or done.stdout).strip().splitlines()[:1]
                    findings.append(Finding('problem', path, f'syntax_error:{detail[0][:200] if detail else argv[0]}'))
    return findings
