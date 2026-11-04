"""Restricted frontmatter reader for SKILL.md (no YAML dependency).

The project deliberately avoids YAML extras, so this reader accepts only the subset a skill needs:

- ``key: value`` lines, where value is a plain string, a quoted string, or a JSON array/object.
- Lists and objects must be written as JSON on one line (``tools: ["read_memory"]``).
- Keys outside :data:`ALLOWED_KEYS` are rejected, so a misspelled key cannot be silently ignored.

Anything else raises :class:`SkillFormatError`. The reader never executes or imports content.
"""
from __future__ import annotations

import json
from typing import Any

ALLOWED_KEYS = frozenset({'name', 'description', 'tools', 'scripts'})
_DELIMITER = '---'


class SkillFormatError(ValueError):
    """Raised with a stable, user-readable message when SKILL.md cannot be accepted."""


def split(markdown: str) -> tuple[dict[str, Any], str]:
    """Return ``(frontmatter, body)`` for a SKILL.md document.

    The document must begin with a ``---`` line, followed by ``key: value`` lines and a closing
    ``---`` line. Everything after the closing line is the body, returned unchanged apart from
    the single newline that follows the delimiter.
    """
    lines = markdown.replace('\r\n', '\n').split('\n')
    if not lines or lines[0].strip() != _DELIMITER:
        raise SkillFormatError('frontmatter_missing')
    try:
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == _DELIMITER)
    except StopIteration:
        raise SkillFormatError('frontmatter_unterminated') from None
    values: dict[str, Any] = {}
    for number, raw in enumerate(lines[1:end], start=2):
        if not raw.strip() or raw.lstrip().startswith('#'):
            continue
        key, sep, value = raw.partition(':')
        key = key.strip()
        if not sep or not key or raw[:1].isspace():
            raise SkillFormatError(f'frontmatter_line_invalid:{number}')
        if key not in ALLOWED_KEYS:
            raise SkillFormatError(f'frontmatter_key_unknown:{key}')
        if key in values:
            raise SkillFormatError(f'frontmatter_key_duplicate:{key}')
        values[key] = _value(value.strip(), number)
    body = '\n'.join(lines[end + 1:])
    return values, body


def _value(text: str, number: int) -> Any:
    """Parse one value: JSON for arrays and objects, quoted or plain text for scalars."""
    if text[:1] in '[{':
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            raise SkillFormatError(f'frontmatter_json_invalid:{number}') from None
    if len(text) >= 2 and text[0] == text[-1] and text[0] in '"\'':
        return text[1:-1]
    return text
