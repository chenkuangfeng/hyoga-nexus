"""SKILL.md frontmatter reader (openspec 2026-11-07-skill-evolution, S1).

The block between the two ``---`` lines is YAML, read with ``yaml.safe_load`` (never ``load``: no object
construction, no code). Skills written by other people are often slightly off, so a failed parse is retried with
two conservative repairs before it is rejected (the approach of WeKnora's ``skill_frontmatter.go``):

- keys indented under a plain scalar (``name: x`` followed by an indented ``version: 1``) are moved to the top level;
- an unquoted ``name`` / ``description`` value that contains a colon is wrapped in quotes.

A repaired document is accepted and marked ``repaired``; the original text is never changed. Keys this platform does
not know are kept verbatim in ``extra`` with a note, not rejected, so skills from other ecosystems can be imported.
A duplicate key is still an error: the later value would silently win.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import yaml

#: Keys this platform acts on.
KNOWN_KEYS = frozenset({'name', 'description', 'tools', 'scripts', 'execution', 'model_invocable', 'user_invocable'})
#: Keys other skill ecosystems commonly add. They are kept in ``extra`` without a note; none of them grants anything.
FOREIGN_KEYS = frozenset({'version', 'license', 'metadata', 'allowed-tools', 'compatibility', 'author', 'tags'})
#: Retained for callers that used the earlier name.
ALLOWED_KEYS = KNOWN_KEYS
_DELIMITER = '---'
_MAX_FRONTMATTER_CHARS = 16_000


class SkillFormatError(ValueError):
    """Raised with a stable, user-readable message when SKILL.md cannot be accepted."""


@dataclass(frozen=True)
class Frontmatter:
    """A parsed document: the keys the platform acts on, everything else, the body and what was fixed on the way."""
    values: dict[str, Any]
    body: str
    extra: dict[str, Any] = field(default_factory=dict)
    notes: tuple[str, ...] = ()
    repaired: bool = False


class _DuplicateKey(Exception):
    def __init__(self, key: str):
        super().__init__(key)
        self.key = key


class _Loader(yaml.SafeLoader):
    """``SafeLoader`` that refuses duplicate mapping keys instead of keeping the last one."""


def _construct_mapping(loader: _Loader, node: yaml.MappingNode, deep: bool = False) -> dict[Any, Any]:
    seen: set[Any] = set()
    for key_node, _ in node.value:
        key = loader.construct_object(key_node, deep=True)
        if key in seen:
            raise _DuplicateKey(str(key))
        seen.add(key)
    return yaml.SafeLoader.construct_mapping(loader, node, deep=deep)


_Loader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping)


def split_document(markdown: str) -> Frontmatter:
    """Parse a SKILL.md document into frontmatter and body.

    Raises :class:`SkillFormatError` (stable codes) when the document has no frontmatter, it is unterminated,
    it is not a YAML mapping, or it repeats a key.
    """
    lines = markdown.replace('\r\n', '\n').split('\n')
    if not lines or lines[0].strip() != _DELIMITER:
        raise SkillFormatError('frontmatter_missing')
    try:
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == _DELIMITER)
    except StopIteration:
        raise SkillFormatError('frontmatter_unterminated') from None
    text = '\n'.join(lines[1:end])
    if len(text) > _MAX_FRONTMATTER_CHARS:
        raise SkillFormatError('frontmatter_too_large')
    loaded, repaired = _load_with_repair(text)
    if loaded is None:
        loaded = {}
    if not isinstance(loaded, dict) or any(not isinstance(key, str) for key in loaded):
        raise SkillFormatError('frontmatter_not_a_mapping')
    values = {key: value for key, value in loaded.items() if key in KNOWN_KEYS}
    extra = {key: _jsonable(value) for key, value in loaded.items() if key not in KNOWN_KEYS}
    notes = [f'frontmatter_key_unknown:{key}' for key in extra if key not in FOREIGN_KEYS]
    if repaired:
        notes.append('frontmatter_repaired')
    return Frontmatter(values=values, body='\n'.join(lines[end + 1:]), extra=extra,
                       notes=tuple(notes), repaired=repaired)


def split(markdown: str) -> tuple[dict[str, Any], str]:
    """Return ``(known keys, body)``; see :func:`split_document` for the rest."""
    parsed = split_document(markdown)
    return parsed.values, parsed.body


def _load_with_repair(text: str) -> tuple[Any, bool]:
    try:
        return _load(text), False
    except yaml.YAMLError as first:
        for candidate in _repair_candidates(text):
            if candidate == text:
                continue
            try:
                return _load(candidate), True
            except yaml.YAMLError:
                continue
        raise SkillFormatError('frontmatter_invalid') from first


def _load(text: str) -> Any:
    try:
        return yaml.load(text, Loader=_Loader)  # noqa: S506 - _Loader is a SafeLoader subclass
    except _DuplicateKey as duplicate:
        raise SkillFormatError(f'frontmatter_key_duplicate:{duplicate.key}') from None


def _repair_candidates(text: str) -> list[str]:
    outdented = _outdent_accidental_nesting(text)
    return [outdented, _quote_colon_values(text), _quote_colon_values(outdented)]


def _leading(line: str) -> int:
    return len(line) - len(line.lstrip(' \t'))


def _is_plain_scalar_mapping(trimmed: str) -> bool:
    if not trimmed or trimmed.startswith('#'):
        return False
    key, sep, value = trimmed.partition(':')
    value = value.strip()
    if not sep or not key.strip() or not value or value.startswith('#'):
        return False
    return not (value[0] in '|>{[')


def _looks_like_key(trimmed: str) -> bool:
    if not trimmed or trimmed[0] in '#-':
        return False
    key, sep, _ = trimmed.partition(':')
    key = key.strip()
    return bool(sep) and bool(re.fullmatch(r'[A-Za-z_][\w.-]*', key) or key[:1] in '"\'')


def _outdent_accidental_nesting(text: str) -> str:
    """Move keys that were indented under a plain scalar (``name: x`` then ``  version: 1``) to the top level.

    A real nested mapping (``metadata:`` with no value on its line) is valid YAML and is left alone.
    """
    lines = text.split('\n')
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        out.append(line)
        i += 1
        if not _is_plain_scalar_mapping(line.strip()):
            continue
        indent = _leading(line)
        while i < len(lines) and not lines[i].strip():
            out.append(lines[i])
            i += 1
        if i >= len(lines):
            break
        next_indent = _leading(lines[i])
        if next_indent <= indent or not _looks_like_key(lines[i].strip()):
            continue
        extra = next_indent - indent
        while i < len(lines):
            current = lines[i]
            if current.strip() and _leading(current) < next_indent:
                break
            out.append(current[min(extra, _leading(current)):] if current.strip() else current)
            i += 1
    return '\n'.join(out)


_COLON_VALUE = re.compile(r'^(\s*(?:name|description)\s*:\s*)([^"\'|>{\[\s#].*:.+)$')


def _quote_colon_values(text: str) -> str:
    """Wrap ``name`` / ``description`` values that contain a colon, so ``description: Foo: bar`` is a string."""
    lines = text.split('\n')
    for index, line in enumerate(lines):
        match = _COLON_VALUE.match(line)
        if match is None:
            continue
        value = match.group(2).strip()
        escaped = value.replace('\\', '\\\\').replace('"', '\\"')
        lines[index] = f'{match.group(1)}"{escaped}"'
    return '\n'.join(lines)


def _jsonable(value: Any) -> Any:
    """Reduce a YAML value to JSON types (dates and similar become strings) so it can be stored."""
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)
