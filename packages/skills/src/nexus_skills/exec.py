"""Running one script of a skill: which file, with which interpreter, as which command line.

Pure rules (openspec 2026-11-07-skill-evolution, S2); nothing here touches a process, the database or the file
system. A skill needs no list of scripts: the file's presence is the declaration, and the installer's scan and checks
have already covered it. The caller supplies the version's files and gets back what to run.

The command line is built from an argument list, every element quoted with ``shlex``, and handed to ``sh -c`` by the
executors. The shell therefore only splits on our quotes: a space, ``;``, ``$( )`` or a glob inside an argument
reaches the script as plain text. The interpreter is chosen from a fixed list by file extension or ``#!`` line;
anything else is refused, so a skill cannot make the platform start an arbitrary program.
"""
from __future__ import annotations

import hashlib
import re
import shlex
from dataclasses import dataclass

from .versions import SkillFileError, normalize_path

#: Interpreter by extension; the names are looked up on the sandbox's ``PATH``.
INTERPRETER_BY_SUFFIX = {'.py': 'python3', '.sh': 'bash', '.bash': 'bash', '.js': 'node', '.mjs': 'node', '.cjs': 'node'}
#: Interpreter named on a ``#!`` line -> the interpreter used.
INTERPRETER_BY_SHEBANG = {'python3': 'python3', 'python': 'python3', 'bash': 'bash', 'sh': 'sh', 'node': 'node'}
MAX_ARGS = 50
MAX_ARG_CHARS = 2000
_SHEBANG = re.compile(r'^#!\s*(?:/usr/bin/env\s+(?:-S\s+)?|/\S*/)?(\w+)')


class ScriptError(ValueError):
    """A script cannot be run; the message is a stable code safe to show to the model."""


@dataclass(frozen=True)
class ResolvedScript:
    """The script chosen for a run: its path inside the skill, the interpreter and the hash of its content."""
    path: str
    interpreter: str
    content_hash: str


def resolve_script(script: str, files: dict[str, str | bytes]) -> ResolvedScript:
    """Find `script` among the version's files and choose its interpreter.

    `skill_script_unavailable`: the path leaves the skill directory or names no file of this version.
    `skill_script_interpreter_not_allowed`: neither the extension nor a ``#!`` line names an allowed interpreter.
    """
    try:
        path = normalize_path(script)
    except SkillFileError:
        raise ScriptError('skill_script_unavailable') from None
    if path not in files:
        raise ScriptError('skill_script_unavailable')
    content = files[path]
    data = content.encode('utf-8') if isinstance(content, str) else content
    interpreter = _interpreter(path, data)
    return ResolvedScript(path, interpreter, hashlib.sha256(data).hexdigest())


def _interpreter(path: str, data: bytes) -> str:
    suffix = '.' + path.rsplit('.', 1)[-1].lower() if '.' in path.rsplit('/', 1)[-1] else ''
    if suffix in INTERPRETER_BY_SUFFIX:
        return INTERPRETER_BY_SUFFIX[suffix]
    first = data.split(b'\n', 1)[0].decode('utf-8', 'replace').strip()
    match = _SHEBANG.match(first) if first.startswith('#!') else None
    if match and match.group(1) in INTERPRETER_BY_SHEBANG:
        return INTERPRETER_BY_SHEBANG[match.group(1)]
    raise ScriptError('skill_script_interpreter_not_allowed')


def check_args(args: object) -> list[str]:
    """Validate the argument list: strings only, bounded in number and length, no NUL byte."""
    if args is None:
        return []
    if (not isinstance(args, list) or len(args) > MAX_ARGS
            or any(not isinstance(item, str) or len(item) > MAX_ARG_CHARS or '\x00' in item for item in args)):
        raise ScriptError('skill_script_args_invalid')
    return list(args)


def build_command(interpreter: str, skill_dir: str, script_path: str, args: list[str], path_prefix: str = '') -> str:
    """The command line: the interpreter, the script inside the skill directory, then each argument, all quoted.

    `path_prefix` (directories of the skill's dependency environment) is put in front of ``PATH`` for this one command,
    so ``python3`` resolves to the environment's interpreter.
    """
    command = shlex.join([interpreter, f"{skill_dir.rstrip('/')}/{script_path}", *args])
    return f'PATH={shlex.quote(path_prefix)}:"$PATH" {command}' if path_prefix else command
