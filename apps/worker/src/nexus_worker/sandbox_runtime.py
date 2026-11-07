"""Process-wide sandbox manager for the worker (openspec 2026-11-07-tool-expansion, section 3).

The manager exists only when `[sandbox].enabled` is true and the settings are valid. A Run gets a session
from it only while the `sandbox` tool group is offered, so a disabled or unaccepted sandbox costs nothing.
"""
from __future__ import annotations

import logging
from functools import lru_cache

from nexus_core.deployment import DeploymentConfigError
from nexus_sandbox.manager import SandboxManager
from nexus_sandbox.settings import load_config

logger = logging.getLogger("nexus_worker.sandbox")


@lru_cache(maxsize=1)
def _config():
    """The parsed `[sandbox]` section, or None when it is off or invalid (logged once)."""
    try:
        config = load_config()
    except DeploymentConfigError:
        logger.error("Invalid [sandbox] configuration; the sandbox stays off")
        return None
    return config if config.enabled else None


_managers: dict[str, SandboxManager] = {}


def manager(profile: str | None = None) -> SandboxManager | None:
    """The shared manager of one profile (the default profile for an empty name), or None when the sandbox is off or
    the profile does not exist. Each profile has its own manager so leases and containers never mix."""
    config = _config()
    settings = config.get(profile) if config is not None else None
    if settings is None:
        return None
    if settings.profile not in _managers:
        _managers[settings.profile] = SandboxManager(settings)
    return _managers[settings.profile]


def managers() -> list[SandboxManager]:
    """Every manager created so far (for reclamation)."""
    return list(_managers.values())


def session_for(tenant_id: str, session_id: str, *, default_timeout: float, output_limit: int, profile: str | None = None):
    """A sandbox session for this Run on the agent's profile, or None when no sandbox is available."""
    current = manager(profile)
    if current is None:
        return None
    return current.session(tenant_id, session_id, default_timeout=default_timeout, output_limit=output_limit)


async def reap_idle() -> None:
    """Remove idle and orphaned session containers of every profile; called from the worker loop, never raises."""
    for current in managers():
        try:
            removed = await current.reap()
            if removed:
                logger.info("Removed %d idle sandbox container(s) of profile %s", len(removed), current.settings.profile)
        except Exception:
            logger.warning("Sandbox reclamation failed", exc_info=True)
