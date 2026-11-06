"""Tool access decisions (openspec 2026-11-06-tool-call-hardening, section D; WeKnora internal/agent/policy).

One pure function combines a tool's `risk` with the agent's access level:

| access \\ risk | read / probe | write | destructive |
| --- | --- | --- | --- |
| `read_only` | allow | deny | deny |
| `standard`  | allow | allow | ask |
| `strict`    | allow | ask | ask |

A tool that declares `requires_approval` turns `allow` into `ask`; `deny` stays `deny`. The gateway calls it
when listing definitions (denied tools are hidden) and again before each call, so a policy can only
tighten what binding and authorization already allow.
"""
from __future__ import annotations

from typing import Literal

Decision = Literal['allow', 'ask', 'deny']

_TABLE: dict[str, dict[str, Decision]] = {
    'read_only': {'read': 'allow', 'probe': 'allow', 'write': 'deny', 'destructive': 'deny'},
    'standard': {'read': 'allow', 'probe': 'allow', 'write': 'allow', 'destructive': 'ask'},
    'strict': {'read': 'allow', 'probe': 'allow', 'write': 'ask', 'destructive': 'ask'},
}


def decide(risk: str, access: str, requires_approval: bool) -> Decision:
    """`allow`, `ask` (needs approval) or `deny`. Unknown risks or access levels are treated as the strictest."""
    decision = _TABLE.get(access, _TABLE['strict']).get(risk, 'ask' if access != 'read_only' else 'deny')
    if decision == 'allow' and requires_approval:
        return 'ask'
    return decision
