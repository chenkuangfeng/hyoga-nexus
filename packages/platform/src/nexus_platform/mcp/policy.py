"""MCP tool risk policy (WeKnora ``internal/agent/approval/mcp_risk.go``).

Only ``readOnlyHint`` lowers a declared risk to ``read``: MCP defaults ``destructiveHint`` to true,
so reading it would make every unannotated tool destructive. Destructive is set by the workspace.
The stored policy never falls below the highest risk the service ever declared, so a service cannot
silently lower its own tool's risk without the workspace agreeing (``pending_downgrade``).
"""
from __future__ import annotations

#: Risk order for the only three MCP risks (``probe`` is a native-only class, never MCP).
RISK_ORDER = ("read", "write", "destructive")
_RISK_RANK = {risk: index for index, risk in enumerate(RISK_ORDER)}
VALID_RISKS = frozenset(RISK_ORDER)


def declared_risk(read_only_hint: bool) -> str:
    """The risk a service's annotations give its tool."""
    return "read" if read_only_hint else "write"


def risk_above(candidate: str, baseline: str) -> bool:
    """True when `candidate` is strictly higher than `baseline`; unknown values never count as higher."""
    return _RISK_RANK.get(candidate, -1) > _RISK_RANK.get(baseline, -1)


def effective_risk(explicit: str | None, observed: str | None, declared: str) -> str:
    """The risk in force: explicit wins, then the highest observed declaration, then the current one."""
    if explicit in VALID_RISKS:
        return explicit
    if observed in VALID_RISKS and risk_above(observed, declared):
        return observed
    return declared if declared in VALID_RISKS else "write"


def pending_downgrade(explicit: str | None, observed: str | None, declared: str) -> bool:
    """Whether the service now declares lower than the observed risk, which only the workspace can accept."""
    return explicit is None and observed in VALID_RISKS and risk_above(observed, declared)


def observe_declared(explicit: str | None, observed: str | None, declared: str) -> str | None:
    """The new observed risk to store, or ``None`` when nothing should change.

    Mirrors WeKnora ``Action``: observe only when there is no row yet, or the declaration rises
    above what was observed, so a service can never lower the recorded maximum on its own.
    """
    if observed not in VALID_RISKS:
        return declared if declared in VALID_RISKS else None
    if risk_above(declared, observed):
        return declared
    return None


def risk_action(
    explicit: str | None,
    observed: str | None,
    declared: str,
    require_approval: bool = False,
) -> tuple[str, bool]:
    """The policy action of calling a tool: its effective risk and whether it always needs approval."""
    return effective_risk(explicit, observed, declared), bool(require_approval)


def fail_close_action() -> tuple[str, bool]:
    """The fail-close action when a policy cannot be read: write risk, always require approval."""
    return "write", True
