"""Process-wide sandbox manager for the worker (openspec 2026-11-07-tool-expansion, section 3).

The manager exists only when `[sandbox].enabled` is true and the settings are valid. A Run gets a session
from it only while the `sandbox` tool group is offered, so a disabled or unaccepted sandbox costs nothing.
"""
from __future__ import annotations

import asyncio
import logging
import time
from functools import lru_cache

from nexus_core.deployment import DeploymentConfigError
from nexus_sandbox.manager import SandboxManager
from nexus_sandbox.settings import apply_profile_policy, configuration_revision, load_config

logger = logging.getLogger("nexus_worker.sandbox")


@lru_cache(maxsize=1)
def _config(revision=None):
    """The parsed `[sandbox]` section, or None when it is off or invalid (logged once)."""
    try:
        config = load_config(include_policies=False)
    except DeploymentConfigError:
        logger.error("Invalid [sandbox] configuration; the sandbox stays off")
        return None
    return config if config.enabled else None


_managers: dict[str, SandboxManager] = {}


def manager(profile: str | None = None) -> SandboxManager | None:
    """The shared manager of one profile (the default profile for an empty name), or None when the sandbox is off or
    the profile does not exist. Each profile has its own manager so leases and containers never mix."""
    try:
        config = _config(configuration_revision())
    except DeploymentConfigError:
        return None
    settings = config.get(profile) if config is not None else None
    if settings is None:
        return None
    try:
        settings = apply_profile_policy(settings)
    except DeploymentConfigError:
        logger.error("Invalid sandbox profile policy")
        return None
    if settings.paused:
        return None
    if settings.profile not in _managers or _managers[settings.profile].settings != settings:
        _managers[settings.profile] = SandboxManager(settings)
    else:
        _managers[settings.profile].settings = settings
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


#: Seconds between reclamation passes. Containers idle for `idle_seconds` (at least 30) are removed, so a minute is fine.
REAP_INTERVAL_SECONDS = 60.0
_last_reap = 0.0


async def reap_periodically(stopped) -> None:
    """Reclaim on a timer until `stopped` is set. Runs on the loop that executes Runs, where the managers' docker
    calls are made; does nothing while no manager exists (sandbox off or no Run used it yet)."""
    while not stopped.is_set():
        await asyncio.sleep(REAP_INTERVAL_SECONDS)
        if managers():
            await reap_idle()


def reap_if_due(loop: asyncio.AbstractEventLoop) -> None:
    """Synchronous loop variant: reclaim on `loop` when the interval has passed since the last pass."""
    global _last_reap
    now = time.monotonic()
    if not managers() or now - _last_reap < REAP_INTERVAL_SECONDS:
        return
    _last_reap = now
    loop.run_until_complete(reap_idle())
