"""Parse and validate one skill definition from SKILL.md.

:func:`parse_skill` is pure: it reads text, returns a :class:`ParsedSkill`, and performs no I/O.
Level 1 (name, description) is what the system prompt shows; Level 2 (``body``) is returned by
``load_skill``; Level 3 (resource files) is read through ``read_skill_file``.

Declared ``scripts`` are validated here but never executed by this module. Execution is a separate
runner that is gated by configuration (see proposal 2026-11-04-skill-scripts).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from . import frontmatter
from .frontmatter import SkillFormatError
from ..versions import normalize_path

NAME_MAX = 64
DESCRIPTION_MAX = 1024
BODY_MAX = 32_000
TOOLS_MAX = 32
SCRIPTS_MAX = 20
#: Names are lower-case letters and digits joined by single hyphens (one path segment, 1-64 characters).
_NAME_RE = re.compile(r'^[a-z0-9]+(?:-[a-z0-9]+)*$')
_TOOL_RE = re.compile(r'^[a-z][a-z0-9_]{0,63}$')
_SCRIPT_NAME_RE = re.compile(r'^[a-z][a-z0-9_-]{0,63}$')
#: Interpreters a script may declare. Anything else is rejected at parse time and at publish time.
SCRIPT_INTERPRETERS = frozenset({'python3', 'bash', 'node'})
SCRIPT_TIMEOUT_DEFAULT = 60
SCRIPT_TIMEOUT_MAX = 300
RESERVED_NAME_WORDS = ('anthropic', 'claude')


@dataclass(frozen=True)
class ScriptSpec:
    """One declared script. ``risk_level`` is always ``high``; it is not configurable per skill."""
    name: str
    path: str
    interpreter: str
    timeout: int = SCRIPT_TIMEOUT_DEFAULT
    args: dict[str, Any] = field(default_factory=dict)
    risk_level: str = 'high'


@dataclass(frozen=True)
class ParsedSkill:
    """Validated skill metadata plus the Level 2 body."""
    name: str
    description: str
    body: str
    tools: tuple[str, ...] = ()
    scripts: tuple[ScriptSpec, ...] = ()
    #: False hides the skill from the model: it is not listed in the skill index and ``load_skill`` refuses it.
    model_invocable: bool = True
    #: Whether a user may invoke the skill directly. Stored and validated; the user-side entry point comes later.
    user_invocable: bool = True
    #: Where the skill's scripts are meant to run: ``sandbox`` (default) or ``local`` (builtin skills only).
    execution: str = 'sandbox'
    #: Frontmatter keys the platform does not act on, kept verbatim.
    extra: dict[str, Any] = field(default_factory=dict)
    #: Non-blocking notes from parsing (unknown keys, a repaired frontmatter).
    notes: tuple[str, ...] = ()


EXECUTION_VALUES = frozenset({'sandbox', 'local'})


def parse_skill(markdown: str) -> ParsedSkill:
    """Validate SKILL.md and return its metadata and body.

    Raises :class:`SkillFormatError` with a stable code (for example ``skill_name_invalid``) when the
    document breaks a rule. The message is safe to show to the author.
    """
    document = frontmatter.split_document(markdown)
    values, body = document.values, document.body
    name = _required_string(values, 'name')
    if len(name) > NAME_MAX or not _NAME_RE.match(name):
        raise SkillFormatError('skill_name_invalid')
    lowered = name.casefold()
    if any(word in lowered for word in RESERVED_NAME_WORDS):
        raise SkillFormatError('skill_name_reserved')
    description = _required_string(values, 'description')
    if len(description) > DESCRIPTION_MAX:
        raise SkillFormatError('skill_description_too_long')
    if len(body) > BODY_MAX:
        raise SkillFormatError('skill_body_too_large')
    tools = _tools(values.get('tools', []))
    scripts = _scripts(values.get('scripts', []))
    execution = values.get('execution', 'sandbox')
    if execution not in EXECUTION_VALUES:
        raise SkillFormatError('skill_execution_invalid')
    flags = {key: values.get(key, True) for key in ('model_invocable', 'user_invocable')}
    if any(not isinstance(value, bool) for value in flags.values()):
        raise SkillFormatError('skill_flag_invalid')
    return ParsedSkill(name=name, description=description, body=body.strip('\n'), tools=tools, scripts=scripts,
                       model_invocable=flags['model_invocable'], user_invocable=flags['user_invocable'],
                       execution=execution, extra=document.extra, notes=document.notes)


def _required_string(values: dict[str, Any], key: str) -> str:
    value = values.get(key)
    if not isinstance(value, str) or not value.strip():
        raise SkillFormatError(f'skill_{key}_missing')
    return value.strip()


def _tools(raw: Any) -> tuple[str, ...]:
    if not isinstance(raw, list) or len(raw) > TOOLS_MAX:
        raise SkillFormatError('skill_tools_invalid')
    names: list[str] = []
    for item in raw:
        if not isinstance(item, str) or not _TOOL_RE.match(item) or item in names:
            raise SkillFormatError('skill_tools_invalid')
        names.append(item)
    return tuple(names)


def _scripts(raw: Any) -> tuple[ScriptSpec, ...]:
    if not isinstance(raw, list) or len(raw) > SCRIPTS_MAX:
        raise SkillFormatError('skill_scripts_invalid')
    specs: list[ScriptSpec] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            raise SkillFormatError('skill_scripts_invalid')
        unknown = set(item) - {'name', 'path', 'interpreter', 'timeout', 'args', 'risk_level'}
        if unknown:
            raise SkillFormatError('skill_scripts_invalid')
        name = item.get('name')
        if not isinstance(name, str) or not _SCRIPT_NAME_RE.match(name) or name in seen:
            raise SkillFormatError('skill_script_name_invalid')
        seen.add(name)
        path = item.get('path')
        if not isinstance(path, str) or not path.startswith('scripts/'):
            raise SkillFormatError('skill_script_path_invalid')
        try:
            normalized = normalize_path(path)
        except ValueError:
            raise SkillFormatError('skill_script_path_invalid') from None
        if not normalized.startswith('scripts/'):
            raise SkillFormatError('skill_script_path_invalid')
        interpreter = item.get('interpreter')
        if interpreter not in SCRIPT_INTERPRETERS:
            raise SkillFormatError('skill_script_interpreter_not_allowed')
        timeout = item.get('timeout', SCRIPT_TIMEOUT_DEFAULT)
        if not isinstance(timeout, int) or isinstance(timeout, bool) or not 1 <= timeout <= SCRIPT_TIMEOUT_MAX:
            raise SkillFormatError('skill_script_timeout_invalid')
        args = item.get('args', {})
        if not isinstance(args, dict):
            raise SkillFormatError('skill_script_args_invalid')
        if args:
            try:
                Draft202012Validator.check_schema(args)
            except SchemaError:
                raise SkillFormatError('skill_script_args_invalid') from None
        if item.get('risk_level', 'high') != 'high':
            raise SkillFormatError('skill_script_risk_invalid')
        specs.append(ScriptSpec(name=name, path=normalized, interpreter=interpreter, timeout=timeout, args=args))
    return tuple(specs)
