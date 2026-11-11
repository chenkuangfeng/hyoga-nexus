"""Fixed catalog of menu keys and backend API permissions that tenant roles may grant.

Roles can only reference keys in this catalog, so a stored grant always names something the
server enforces. Adding a key here is a contract change: it needs a matching enforcement point.
"""
from __future__ import annotations

from nexus_platform.errors import InvalidConfiguration

MENUS: frozenset[str] = frozenset({"chat", "agents", "models", "audit", "members", "roles"})

API_PERMISSIONS: frozenset[str] = frozenset({
    "agents:read",
    "agents:write",
    "agents:publish",
    "sessions:write",
    "runs:write",
    "models:read",
    "models:manage",
    "audit:read",
    "members:manage",
    "roles:manage",
    "org:manage",
    "tools:manage",
    "skills:submit",
    # Maintain enterprise-owned agents / knowledge bases (openspec 2026-11-11-enterprise-saas decision 2).
    # Not governance keys: owners and admins hold them by default and may grant them to custom roles.
    "enterprise_agents:manage",
    "enterprise_kbs:manage",
})


# Agent-level permissions. ``edit``, ``publish`` and ``manage`` come only from ownership (the creator of a personal
# agent, or a holder of ``enterprise_agents:manage`` for an enterprise agent); see ``agents.access``. Roles may grant
# only the use permissions in ``GRANTABLE_AGENT_PERMISSIONS`` (openspec 2026-11-11-enterprise-saas decision 2).
AGENT_PERMISSIONS: frozenset[str] = frozenset({"view", "run", "edit", "publish", "manage"})
GRANTABLE_AGENT_PERMISSIONS: frozenset[str] = frozenset({"view", "run"})
AGENT_IMPLIED: dict[str, frozenset[str]] = {
    "view": frozenset({"view"}),
    "run": frozenset({"run"}),
}


def expand_agent_permissions(granted) -> frozenset[str]:
    """Return the use permissions of stored grants as written. Unknown (pre-migration) values grant nothing."""
    expanded: set[str] = set()
    for permission in granted:
        expanded |= AGENT_IMPLIED.get(permission, frozenset())
    return frozenset(expanded)


def validate_agent_permissions(permissions) -> frozenset[str]:
    """Normalize the permissions a role assignment grants; only ``view`` and ``run`` are assignable."""
    permission_set = frozenset(permissions)
    unknown = permission_set - GRANTABLE_AGENT_PERMISSIONS
    if unknown:
        raise InvalidConfiguration(f"Unknown agent permission: {', '.join(sorted(unknown))}")
    return permission_set


def validate_grants(menus, apis) -> tuple[frozenset[str], frozenset[str]]:
    """Return normalized grant sets, rejecting any key outside the catalog."""
    menu_set, api_set = frozenset(menus), frozenset(apis)
    unknown = (menu_set - MENUS) | (api_set - API_PERMISSIONS)
    if unknown:
        raise InvalidConfiguration(f"Unknown menu or API permission: {', '.join(sorted(unknown))}")
    return menu_set, api_set
