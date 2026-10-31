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
})


def validate_grants(menus, apis) -> tuple[frozenset[str], frozenset[str]]:
    """Return normalized grant sets, rejecting any key outside the catalog."""
    menu_set, api_set = frozenset(menus), frozenset(apis)
    unknown = (menu_set - MENUS) | (api_set - API_PERMISSIONS)
    if unknown:
        raise InvalidConfiguration(f"Unknown menu or API permission: {', '.join(sorted(unknown))}")
    return menu_set, api_set
