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
    #: Latest isolation acceptance passed for the agent's sandbox profile (or, for a `local` profile, the operator
    #: allowed it in development mode).
    sandbox_accepted: bool = False
    #: Why an enabled sandbox is not usable when that is not simply "no accepted report": an unknown profile name or
    #: a `local` profile outside development mode.
    sandbox_reason: str = ''
    #: The operator enabled outbound web access (`[web].enabled`).
    web_enabled: bool = False
    #: The agent binds a Wiki-type knowledge base. Wiki tools arrive with knowledge-base K6.1.
    wiki_base_bound: bool = False


def _sandbox(facts: GateFacts) -> str:
    if not facts.sandbox_enabled:
        return 'sandbox_disabled'
    if facts.sandbox_accepted:
        return ''
    return facts.sandbox_reason or 'sandbox_not_accepted'


#: group id -> check returning '' when available, else a stable reason code. Groups missing here are always
#: available (``base``, ``memory``, ``knowledge``, ``skills``: their own switches live elsewhere).
AVAILABILITY: dict[str, Callable[[GateFacts], str]] = {
    'sandbox': _sandbox,
    'wiki': lambda facts: '' if facts.wiki_base_bound else 'wiki_base_not_bound',
    # Image files live in the sandbox workspace, so the media tools need a usable sandbox.
    'media': lambda facts: '' if _sandbox(facts) == '' else 'sandbox_required',
    'web': lambda facts: '' if facts.web_enabled else 'web_disabled',
}


def unavailable_groups(facts: GateFacts) -> dict[str, str]:
    """Group id -> reason for every group that is not available under `facts`."""
    reasons = {group: check(facts) for group, check in AVAILABILITY.items()}
    return {group: reason for group, reason in reasons.items() if reason}


def hidden_groups(facts: GateFacts, switches: dict[str, bool] | None) -> frozenset[str]:
    """Groups to hide from a Run: unavailable ones plus those the agent switched off."""
    unavailable = unavailable_groups(facts)
    return frozenset(group for group in GROUP_IDS if group in unavailable or not group_enabled(switches, group))


def profile_facts(config, settings, web_enabled: bool = False) -> GateFacts:
    """Gate facts for one sandbox profile of an enabled `[sandbox]` section (`settings` None: no such profile)."""
    from nexus_platform.configuration import auth_settings
    from nexus_sandbox import acceptance
    from nexus_sandbox.settings import sandbox_local_allowed
    if settings is None:
        return GateFacts(sandbox_enabled=True, sandbox_reason='sandbox_profile_unknown', web_enabled=web_enabled)
    if settings.backend == 'local':
        allowed = sandbox_local_allowed(settings, development_mode=auth_settings().mode == 'development')
        return GateFacts(sandbox_enabled=True, sandbox_accepted=allowed,
                         sandbox_reason='' if allowed else 'sandbox_local_not_allowed', web_enabled=web_enabled)
    return GateFacts(sandbox_enabled=True, sandbox_accepted=acceptance.passed(settings), web_enabled=web_enabled)


def deployment_gate_facts(profile: str | None = None) -> GateFacts:
    """Facts read from the deployment for one agent: whether the sandbox is enabled and its profile usable.

    `profile` is the agent's `sandbox_profile`; empty or None takes the deployment's default profile. A stored
    isolation report counts only when it matches that profile's backend, image and limits. A `local` profile never
    passes acceptance: it is usable only when the operator set `allow_local` and the platform runs in development
    auth mode (reason `sandbox_local_not_allowed` otherwise). A broken `[sandbox]` section leaves the group
    unavailable rather than failing the Run.
    """
    from nexus_core.deployment import DeploymentConfigError
    web_enabled = _web_enabled()
    try:
        from nexus_sandbox.settings import load_config
        config = load_config()
    except DeploymentConfigError:
        return GateFacts(web_enabled=web_enabled)
    if not config.enabled:
        return GateFacts(web_enabled=web_enabled)
    return profile_facts(config, config.get(profile), web_enabled)


def sandbox_profiles() -> list[dict]:
    """Every profile the operator defined, for the agent editor: name, type, whether it is the default and, when
    it cannot be used, the stable reason code. Empty when the sandbox is off or its configuration is broken."""
    from nexus_core.deployment import DeploymentConfigError
    try:
        from nexus_sandbox.settings import load_config
        config = load_config()
    except DeploymentConfigError:
        return []
    if not config.enabled:
        return []
    listed = []
    for name, settings in config.profiles.items():
        reason = _sandbox(profile_facts(config, settings))
        listed.append({'name': name, 'type': settings.backend, 'default': name == config.default_profile,
                       'available': not reason, 'reason': reason})
    return listed


def _web_enabled() -> bool:
    """Whether `[web].enabled` is true. A missing or broken section means off."""
    from nexus_core.deployment import DeploymentConfigError
    try:
        from nexus_tools.web.settings import load_settings
        return load_settings().enabled
    except (DeploymentConfigError, ImportError):
        return False
