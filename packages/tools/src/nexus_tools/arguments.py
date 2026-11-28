"""Tool-argument tolerance: JSON repair, schema-guided coercion, readable validation errors.

openspec 2026-11-06-tool-call-hardening, section A. Models often emit almost-right arguments: a trailing
comma, `"5"` for an integer, a JSON-encoded string where an array is expected. Failing those wastes a
model call; accepting truncated arguments would run a tool with half its input. The rules here repair
only what is unambiguous and report the rest precisely.

- `repair_json` ports WeKnora `RepairJSONDetail` (internal/agent/tools/json_repair.go). Anything that
  needs an unclosed string or bracket closed is reported as truncated and must not run.
- `coerce` ports hermes-agent `coerce_tool_args` (tools/arg_coercion.py): only top-level properties,
  local `$ref` resolved, originals kept whenever a repair is not certain.
- Legacy aliases are normalized to one canonical field before schema validation; the canonical value wins.
- `describe_errors` formats jsonschema errors (WeKnora `FormatValidationErrors`) without echoing values,
  so long or sensitive argument text is never sent back to the model.

Pure functions: no I/O, no registry access.
"""
from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import unquote

from jsonschema import Draft202012Validator

#: Bounds of the error text returned to the model.
MAX_ERRORS = 5
MAX_ERROR_CHARS = 1000
LEGACY_ARGUMENT_ALIASES = {
    # GenericAgent's checkpoint contract uses `key_info`; older Nexus calls used `content`.
    'update_working_checkpoint': {'content': 'key_info'},
}


# ---------------------------------------------------------------- JSON repair

def repair_json(text: str) -> tuple[str, bool]:
    """Repair malformed JSON object text. Returns `(repaired, truncated)`.

    Fixes, in order: invalid escapes inside strings, content after the top-level value, trailing commas
    before `}` / `]`, and single quotes used as string delimiters when the text has no double quotes.
    `truncated` is True when an unclosed string or bracket had to be closed: such arguments were cut off
    and the call must be refused, not repaired.
    """
    text = (text or '').strip()
    if not text:
        return '{}', False
    if '"' not in text and "'" in text:
        text = text.replace("'", '"')
    if text[0] != '{':
        if ':' in text:
            text = '{' + text + '}'
        else:
            return text, False
    text = _fix_invalid_escapes(text)
    text = _trim_after_top_level_value(text)
    text = _fix_trailing_commas(text)
    return _balance_brackets(text)


def _fix_invalid_escapes(text: str) -> str:
    out: list[str] = []
    in_string = False
    i = 0
    while i < len(text):
        char = text[i]
        if not in_string:
            out.append(char)
            in_string = char == '"'
        elif char == '"':
            out.append(char)
            in_string = False
        elif char != '\\':
            out.append(char)
        elif i + 1 >= len(text):
            out.append('\\\\')
        else:
            following = text[i + 1]
            out.append(char + following if following in '"\\/bfnrtu' else '\\\\' + following)
            i += 1
        i += 1
    return ''.join(out)


def _trim_after_top_level_value(text: str) -> str:
    depth, in_string, escaped = 0, False, False
    for index, char in enumerate(text):
        if escaped:
            escaped = False
            continue
        if in_string:
            if char == '\\':
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char in '{[':
            depth += 1
        elif char in '}]':
            depth -= 1
            if depth == 0:
                return text if not text[index + 1:].strip() else text[:index + 1]
    return text


def _fix_trailing_commas(text: str) -> str:
    out: list[str] = []
    in_string, escaped = False, False
    for index, char in enumerate(text):
        if escaped:
            escaped = False
            out.append(char)
            continue
        if char == '\\' and in_string:
            escaped = True
            out.append(char)
            continue
        if char == '"':
            in_string = not in_string
        elif not in_string and char == ',':
            rest = text[index + 1:].lstrip()
            if rest[:1] in ('}', ']'):
                continue
        out.append(char)
    return ''.join(out)


def _balance_brackets(text: str) -> tuple[str, bool]:
    stack: list[str] = []
    in_string, escaped = False, False
    for char in text:
        if escaped:
            escaped = False
            continue
        if char == '\\' and in_string:
            escaped = True
            continue
        if char == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if char == '{':
            stack.append('}')
        elif char == '[':
            stack.append(']')
        elif char in '}]' and stack and stack[-1] == char:
            stack.pop()
    closed = False
    if in_string:
        text += '"'
        closed = True
    for closer in reversed(stack):
        text += closer
        closed = True
    return text, closed


# ---------------------------------------------------------------- coercion

def coerce(arguments: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
    """Coerce top-level argument values to the types their schema expects; a new dict, originals kept.

    - strings to `integer` / `number` / `boolean` / `null` only for unambiguous spellings;
    - strings to `array` / `object` only when `json.loads` succeeds with the right container type,
      recursing into containers so nested JSON-encoded strings are parsed where a container is expected;
    - a scalar where an `array` is expected becomes a one-element array.
    """
    properties = schema.get('properties') if isinstance(schema, dict) else None
    if not isinstance(arguments, dict) or not isinstance(properties, dict):
        return arguments
    out = dict(arguments)
    for key, value in arguments.items():
        prop = properties.get(key)
        if not isinstance(prop, dict):
            continue
        prop = _resolve_ref(prop, schema)
        expected = prop.get('type')
        is_container = isinstance(value, list)
        if expected == 'array' and value is not None and not is_container:
            if isinstance(value, str):
                parsed = _coerce_value(value, 'array', prop)
                if parsed is not value:
                    out[key] = _normalize(parsed, prop, schema)
                    continue
            out[key] = [value]
            continue
        if not isinstance(value, str):
            if (expected == 'array' and is_container) or (expected == 'object' and isinstance(value, dict)):
                out[key] = _normalize(value, prop, schema)
            continue
        if not expected and not _allows_null(prop):
            continue
        coerced = _coerce_value(value, expected, prop)
        if coerced is not value:
            out[key] = _normalize(coerced, prop, schema) if isinstance(coerced, (list, dict)) else coerced
    return out


def normalize_legacy_aliases(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Map retired argument names to the current schema, preferring an explicit canonical value."""
    aliases = LEGACY_ARGUMENT_ALIASES.get(tool_name)
    if not aliases or not any(alias in arguments for alias in aliases):
        return arguments
    normalized = dict(arguments)
    for alias, canonical in aliases.items():
        if alias in normalized:
            normalized.setdefault(canonical, normalized[alias])
            del normalized[alias]
    return normalized


_BAD_POINTER_ESCAPE = re.compile(r'~(?![01])')


def _resolve_ref(schema: Any, root: Any, seen: frozenset[str] = frozenset()) -> Any:
    """Follow a document-local `$ref` (JSON Pointer); remote, malformed or cyclic refs come back unchanged."""
    if not isinstance(schema, dict) or not isinstance(root, dict):
        return schema
    ref = schema.get('$ref')
    if not isinstance(ref, str) or not ref.startswith('#') or ref in seen:
        return schema
    pointer = unquote(ref[1:])
    if pointer and not pointer.startswith('/'):
        return schema
    target: Any = root
    for raw in pointer.split('/')[1:]:
        if _BAD_POINTER_ESCAPE.search(raw):
            return schema
        token = raw.replace('~1', '/').replace('~0', '~')
        if isinstance(target, dict) and token in target:
            target = target[token]
        elif isinstance(target, list) and token.isdigit() and int(token) < len(target):
            target = target[int(token)]
        else:
            return schema
    if not isinstance(target, dict):
        return schema
    merged = {**{k: v for k, v in schema.items() if k != '$ref'}, **target}
    return _resolve_ref(merged, root, seen | {ref})


def _accepts(schema: Any, kind: str, root: Any) -> bool:
    if not isinstance(schema, dict):
        return False
    schema = _resolve_ref(schema, root)
    declared = schema.get('type')
    if declared == kind or (isinstance(declared, list) and kind in declared):
        return True
    return any(isinstance(schema.get(key), list) and any(_accepts(branch, kind, root) for branch in schema[key])
               for key in ('anyOf', 'oneOf', 'allOf'))


def _normalize(value: Any, schema: Any, root: Any) -> Any:
    """Parse JSON-encoded strings found where the schema expects a container, recursively."""
    if not isinstance(schema, dict):
        return value
    schema = _resolve_ref(schema, root)
    if isinstance(value, str):
        trimmed = value.strip()
        wants_array, wants_object = _accepts(schema, 'array', root), _accepts(schema, 'object', root)
        if not ((wants_array and trimmed.startswith('[')) or (wants_object and trimmed.startswith('{'))):
            return value
        try:
            parsed = json.loads(trimmed)
        except (ValueError, TypeError, RecursionError):
            return value
        if not ((isinstance(parsed, list) and wants_array) or (isinstance(parsed, dict) and wants_object)):
            return value
        value = parsed
    if isinstance(value, list) and isinstance(schema.get('items'), dict):
        return [_normalize(item, schema['items'], root) for item in value]
    if isinstance(value, dict) and isinstance(schema.get('properties'), dict):
        out = dict(value)
        for key, prop in schema['properties'].items():
            if key in value:
                out[key] = _normalize(value[key], prop, root)
        return out
    return value


def _allows_null(schema: Any) -> bool:
    if not isinstance(schema, dict):
        return False
    declared = schema.get('type')
    if declared == 'null' or (isinstance(declared, list) and 'null' in declared) or schema.get('nullable') is True:
        return True
    return any(isinstance(schema.get(key), list) and any(isinstance(v, dict) and v.get('type') == 'null'
                                                        for v in schema[key]) for key in ('anyOf', 'oneOf'))


def _coerce_value(value: str, expected: Any, schema: dict | None) -> Any:
    if _allows_null(schema) and value.strip().lower() == 'null':
        return None
    if isinstance(expected, list):
        for kind in expected:
            result = _coerce_value(value, kind, schema)
            if result is not value:
                return result
        return value
    if expected in ('integer', 'number'):
        try:
            number = float(value)
        except (ValueError, OverflowError):
            return value
        if number != number or number in (float('inf'), float('-inf')):
            return value
        if number == int(number):
            return int(number)
        return value if expected == 'integer' else number
    if expected == 'boolean':
        return {'true': True, 'false': False}.get(value.strip().lower(), value)
    if expected in ('array', 'object'):
        try:
            parsed = json.loads(value)
        except (ValueError, TypeError, RecursionError):
            return value
        return parsed if isinstance(parsed, list if expected == 'array' else dict) else value
    if expected == 'null' and value.strip().lower() == 'null':
        return None
    return value


# ---------------------------------------------------------------- validation errors

def describe_errors(schema: dict[str, Any], arguments: Any) -> str:
    """Readable validation errors: `参数 <path>：<reason>`, path-sorted, at most `MAX_ERRORS`, bounded length.

    Reasons name the violated constraint, never the submitted value. Returns '' when the arguments are valid.
    """
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(arguments), key=lambda e: [str(p) for p in e.absolute_path])
    lines = []
    for error in errors[:MAX_ERRORS]:
        path = '.'.join(str(part) for part in error.absolute_path) or '(根)'
        lines.append(f'参数 {path}：{_reason(error)}')
    text = '\n'.join(lines)
    if len(errors) > MAX_ERRORS:
        text += f'\n（另有 {len(errors) - MAX_ERRORS} 处错误）'
    return text[:MAX_ERROR_CHARS]


def _reason(error) -> str:
    validator, expected = error.validator, error.validator_value
    if validator == 'required':
        missing = [name for name in expected if isinstance(error.instance, dict) and name not in error.instance]
        return '缺少必填字段 ' + '、'.join(missing)
    if validator == 'type':
        return f'类型应为 {expected}'
    if validator == 'enum':
        return '取值应为 ' + ' / '.join(json.dumps(item, ensure_ascii=False) for item in expected)[:200]
    if validator == 'additionalProperties':
        extra = sorted(set(error.instance) - set(error.schema.get('properties', {}))) if isinstance(error.instance, dict) else []
        return '不允许的字段 ' + '、'.join(extra)[:200]
    bounds = {'minimum': '不能小于', 'maximum': '不能大于', 'exclusiveMinimum': '必须大于', 'exclusiveMaximum': '必须小于',
              'minLength': '长度不能少于', 'maxLength': '长度不能超过', 'minItems': '元素数不能少于',
              'maxItems': '元素数不能超过', 'pattern': '格式应匹配', 'const': '取值应为', 'format': '格式应为'}
    if validator in bounds:
        return f'{bounds[validator]} {expected}'
    return f'不满足约束 {validator}'
