"""Tool group availability and the set of groups hidden from one Run (openspec 2026-11-07-tool-expansion, R1).

Two layers decide whether a group's tools are offered:

1. *Availability*: a deployment-side fact, for example "the sandbox backend passed isolation acceptance". When it
   is false the tools do not exist for the Run, and the editor shows the stable reason code.
2. *Agent switch*: ``NativePolicy.tool_groups_enabled``, falling back to each group's ``default_enabled``.

The result is a set of hidden group ids handed to the tool gateway. It only narrows access: binding, live
authorization, access level, guard and approval still apply to every call that gets through. The memory,
knowledge and skill-script gates of earlier changes keep their name-based filters in ``preparation.py``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from nexus_core.native import GROUP_IDS, group_enabled


@dataclass(frozen=True)
class GateFacts:
    """Deployment facts the availability checks read. Built once per process or request, never per tool call."""
    sandbox_enabled: bool = False
    #: Latest isolation acceptance passed for the configured backend, image and settings.
    sandbox_accepted: bool = False
    web_backend_configured: bool = False
    #: The agent binds a Wiki-type knowledge base. Wiki tools arrive with knowledge-base K6.1.
    wiki_base_bound: bool = False


def _sandbox(facts: GateFacts) -> str:
    if not facts.sandbox_enabled:
        return 'sandbox_disabled'
    return '' if facts.sandbox_accepted else 'sandbox_not_accepted'


#: group id -> check returning '' when available, else a stable reason code. Groups missing here are always
#: available (``base``, ``memory``, ``knowledge``, ``skills``: their own switches live elsewhere).
AVAILABILITY: dict[str, Callable[[GateFacts], str]] = {
    'sandbox': _sandbox,
    'wiki': lambda facts: '' if facts.wiki_base_bound else 'wiki_base_not_bound',
    'web': lambda facts: '' if facts.web_backend_configured else 'web_backend_missing',
}


def unavailable_groups(facts: GateFacts) -> dict[str, str]:
    """Group id -> reason for every group that is not available under `facts`."""
    reasons = {group: check(facts) for group, check in AVAILABILITY.items()}
    return {group: reason for group, reason in reasons.items() if reason}


def hidden_groups(facts: GateFacts, switches: dict[str, bool] | None) -> frozenset[str]:
    """Groups to hide from a Run: unavailable ones plus those the agent switched off."""
    unavailable = unavailable_groups(facts)
    return frozenset(group for group in GROUP_IDS if group in unavailable or not group_enabled(switches, group))


def deployment_gate_facts() -> GateFacts:
    """Facts read from the deployment: whether the sandbox is enabled and accepted. The web section is filled in
    when the web tools land (openspec 2026-11-07-tool-expansion, stage E).

    The sandbox counts as accepted when a stored isolation report matches the current backend, image and limits.
    The `local` backend never passes acceptance; it is offered only when the operator set `allow_local` and the
    platform runs in development auth mode, the same gate skill scripts use. A broken `[sandbox]` section
    leaves the group unavailable rather than failing the Run.
    """
    from nexus_core.deployment import DeploymentConfigError
    try:
        from nexus_sandbox import acceptance
        from nexus_sandbox.settings import load_settings
        settings = load_settings()
    except DeploymentConfigError:
        return GateFacts()
    if not settings.enabled:
        return GateFacts()
    if settings.backend == 'local':
        from nexus_platform.configuration import auth_settings
        return GateFacts(sandbox_enabled=True, sandbox_accepted=settings.allow_local and auth_settings().mode == 'development')
    return GateFacts(sandbox_enabled=True, sandbox_accepted=acceptance.passed(settings))
