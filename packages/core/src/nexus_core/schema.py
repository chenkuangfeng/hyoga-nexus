"""Provider-safe copies of tool parameter schemas (openspec 2026-11-07-tool-expansion, R4).

Registered definitions stay as their authors wrote them; the model client sends `sanitize(...)` of them.
Ported from Hermes `tools/schema_sanitizer.py`, keeping the rules that make real providers answer 400:

- property names must match ``[a-zA-Z0-9_.-]{1,64}`` (one bad key anywhere in the tools array fails the whole
  request); offending names are renamed deterministically and `restore` maps the model's arguments back;
- an object needs `properties` and a list `required`; legacy boolean `required` flags are lifted to the parent;
- `type` arrays become one type (`["string", "null"]` → `string` + `nullable`) or an `anyOf`;
- `default` beside `$ref` is dropped; the top level is always a plain object without `allOf` / `anyOf` /
  `oneOf` / `enum` / `not`.
"""
from __future__ import annotations

import copy
import re
from typing import Any

_KEY = re.compile(r'[a-zA-Z0-9_.-]{1,64}')
_BAD = re.compile(r'[^a-zA-Z0-9_.-]')
_TOP_FORBIDDEN = ('allOf', 'anyOf', 'oneOf', 'enum', 'not')
_MAP_KEYS = ('properties', '$defs', 'definitions', 'patternProperties')
_CHILD_KEYS = ('items', 'additionalProperties', 'anyOf', 'oneOf', 'allOf', 'not', 'if', 'then', 'else')


def _renames(properties: dict) -> dict[str, str]:
    """{original: conforming} for the keys of one `properties` mapping that need a new name (insertion order,
    numeric suffix on collision), so the model-visible schema and `restore` always agree."""
    taken = {key for key in properties if _KEY.fullmatch(key)}
    result: dict[str, str] = {}
    for key in (k for k in properties if not _KEY.fullmatch(k)):
        base = (_BAD.sub('_', key)[:60] or 'param')
        candidate, number = base, 1
        while candidate in taken:
            number += 1
            candidate = f'{base}_{number}'
        taken.add(candidate)
        result[key] = candidate
    return result


def _type_array(value: list, out: dict) -> None:
    kinds = [kind for kind in value if kind != 'null']
    if 'null' in value:
        out['nullable'] = True
    if len(kinds) == 1:
        out['type'] = kinds[0]
    elif kinds:
        out['anyOf'] = [{'type': kind} for kind in kinds]
    else:
        out['type'] = 'null'


def _node(node: Any) -> Any:
    if isinstance(node, list):
        return [_node(item) for item in node]
    if not isinstance(node, dict):
        return copy.deepcopy(node)
    properties = node.get('properties')
    renames = _renames(properties) if isinstance(properties, dict) else {}
    out: dict = {}
    for key, value in node.items():
        if key == 'type' and isinstance(value, list):
            _type_array(value, out)
        elif key in _MAP_KEYS and isinstance(value, dict):
            out[key] = {(renames.get(k, k) if key == 'properties' else k): _node(v) for k, v in value.items()}
        elif key == 'required':
            if isinstance(value, list):
                out[key] = [renames.get(item, item) if isinstance(item, str) else item for item in value]
            # a legacy boolean flag is lifted below
        elif key in _CHILD_KEYS:
            out[key] = value if isinstance(value, bool) else _node(value)
        else:
            out[key] = copy.deepcopy(value)  # defaults, consts and metadata are data, not schemas
    if isinstance(properties, dict):
        lifted = [renames.get(k, k) for k, v in properties.items() if isinstance(v, dict) and v.get('required') is True]
        if lifted:
            required = out.get('required') if isinstance(out.get('required'), list) else []
            out['required'] = required + [item for item in lifted if item not in required]
    if '$ref' in out:
        out.pop('default', None)
    if out.get('type') == 'object' or 'properties' in out:
        out.setdefault('properties', {})
        required = out.get('required')
        out['required'] = [item for item in required if isinstance(item, str) and item in out['properties']] \
            if isinstance(required, list) else []
    return out


def sanitize(schema: Any) -> dict:
    """A provider-safe deep copy of a tool's parameter schema; always an object schema."""
    if not isinstance(schema, dict):
        return {'type': 'object', 'properties': {}, 'required': []}
    top = _node(schema)
    top = top if isinstance(top, dict) else {}
    top['type'] = 'object'
    for key in _TOP_FORBIDDEN:
        top.pop(key, None)
    if not isinstance(top.get('properties'), dict):
        top['properties'] = {}
    if not isinstance(top.get('required'), list):
        top['required'] = []
    return top


def restore(arguments: Any, schema: Any) -> Any:
    """Undo `sanitize`'s property renames in arguments the model produced against the sanitized schema."""
    if isinstance(arguments, dict) and isinstance(schema, dict):
        properties = schema.get('properties')
        if isinstance(properties, dict):
            back = {new: old for old, new in _renames(properties).items()}
            return {back.get(key, key): restore(value, properties.get(back.get(key, key))) for key, value in arguments.items()}
        extra = schema.get('additionalProperties')
        if isinstance(extra, dict):
            return {key: restore(value, extra) for key, value in arguments.items()}
    if isinstance(arguments, list) and isinstance(schema, dict) and isinstance(schema.get('items'), dict):
        return [restore(item, schema['items']) for item in arguments]
    return arguments
