"""Argument guard (openspec 2026-11-06-tool-call-hardening, section F; octop-harness `security/tool_guard`).

Bundled rules scan the string values of a call's arguments after authorization and before approval:

- `CRITICAL`: refuse with `tool_guard_denied`, whatever was approved or granted (hermes `approval_floors`);
- `HIGH`: ask a person (`reason='guard'`); a session grant never skips it;
- `MEDIUM` / `LOW`: record only.

Rule fields follow octop-harness YAML (`id`, `tools`, `params`, `category`, `severity`, `patterns`,
`exclude_patterns`, `description`, `remediation`); files are JSON so no YAML dependency is needed.
`params` lists top-level argument names, or `*` for every string value at any depth. Patterns are compiled
at load and matched case-insensitively against the value and its de-obfuscated form (quotes and
backslashes that split words removed, as in hermes `_deny_command_variants`), so `r\\m` or `"r""m"`
does not slip past `rm`. A malformed rule file raises `GuardRuleError`: the gateway must not start with
a guard it cannot enforce.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

RULES_DIR = Path(__file__).resolve().parent / 'rules'
BUNDLED = ('dangerous_shell_commands.json', 'skill_scripts.json')
SEVERITIES = ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')
#: Characters scanned per value; longer values are cut before matching.
MAX_VALUE_CHARS = 20000


class GuardRuleError(ValueError):
    """A bundled rule file is malformed."""


@dataclass(frozen=True)
class Rule:
    id: str
    tools: tuple[str, ...]
    params: tuple[str, ...]
    severity: str
    patterns: tuple[re.Pattern[str], ...]
    excludes: tuple[re.Pattern[str], ...]
    description: str
    remediation: str

    def applies(self, tool: str) -> bool:
        return not self.tools or tool in self.tools


@dataclass(frozen=True)
class Finding:
    rule_id: str
    severity: str
    param: str
    description: str
    remediation: str


def _rule(data: Any, origin: str) -> Rule:
    if not isinstance(data, dict) or not isinstance(data.get('id'), str):
        raise GuardRuleError(f'{origin}: each rule needs an id')
    severity = data.get('severity')
    if severity not in SEVERITIES:
        raise GuardRuleError(f'{origin}: rule {data["id"]} has unknown severity {severity!r}')
    try:
        patterns = tuple(re.compile(p, re.IGNORECASE) for p in data.get('patterns') or [])
        excludes = tuple(re.compile(p, re.IGNORECASE) for p in data.get('exclude_patterns') or [])
    except (re.error, TypeError) as exc:
        raise GuardRuleError(f'{origin}: rule {data["id"]} has a bad pattern: {exc}') from None
    if not patterns:
        raise GuardRuleError(f'{origin}: rule {data["id"]} has no patterns')
    tools, params = data.get('tools') or [], data.get('params') or ['*']
    if isinstance(tools, str):
        tools = [tools]
    if isinstance(params, str):
        params = [params]
    return Rule(data['id'], tuple(tools), tuple(params), severity, patterns, excludes,
                str(data.get('description', '')), str(data.get('remediation', '')))


def load_rules(paths: Iterable[Path]) -> tuple[Rule, ...]:
    rules: list[Rule] = []
    for path in paths:
        try:
            document = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError) as exc:
            raise GuardRuleError(f'{path.name}: cannot read rules: {exc}') from None
        items = document.get('rules') if isinstance(document, dict) else document
        if not isinstance(items, list):
            raise GuardRuleError(f'{path.name}: rules must be a list')
        rules.extend(_rule(item, path.name) for item in items)
    ids = [rule.id for rule in rules]
    if len(ids) != len(set(ids)):
        raise GuardRuleError('Duplicate guard rule id')
    return tuple(rules)


@lru_cache(maxsize=1)
def bundled_rules() -> tuple[Rule, ...]:
    """The rules shipped with `nexus_tools`, loaded once per process."""
    return load_rules(RULES_DIR / name for name in BUNDLED)


_SPLITTERS = re.compile(r'\\(?=\S)|["\']')


def variants(value: str) -> tuple[str, ...]:
    """The value and its de-obfuscated form (word-splitting quotes and backslashes removed)."""
    value = value[:MAX_VALUE_CHARS]
    folded = _SPLITTERS.sub('', value)
    return (value,) if folded == value else (value, folded)


def _strings(value: Any, path: str) -> Iterable[tuple[str, str]]:
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from _strings(item, f'{path}.{key}' if path else str(key))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _strings(item, f'{path}[{index}]')


def scan(tool: str, arguments: dict[str, Any], rules: tuple[Rule, ...] | None = None) -> list[Finding]:
    """Findings for one call, at most one per rule, most severe first."""
    rules = bundled_rules() if rules is None else rules
    findings: list[Finding] = []
    for rule in rules:
        if not rule.applies(tool):
            continue
        for key in arguments if isinstance(arguments, dict) else ():
            if '*' not in rule.params and key not in rule.params:
                continue
            hit = None
            for path, text in _strings(arguments[key], key):
                forms = variants(text)
                if any(ex.search(form) for ex in rule.excludes for form in forms):
                    continue
                if any(pattern.search(form) for pattern in rule.patterns for form in forms):
                    hit = path
                    break
            if hit is not None:
                findings.append(Finding(rule.id, rule.severity, hit, rule.description, rule.remediation))
                break
    findings.sort(key=lambda f: -SEVERITIES.index(f.severity))
    return findings
