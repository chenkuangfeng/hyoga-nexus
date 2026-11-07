"""Process-wide sandbox manager for the worker (openspec 2026-11-07-tool-expansion, section 3).

The manager exists only when `[sandbox].enabled` is true and the settings are valid. A Run gets a session
from it only while the `sandbox` tool group is offered, so a disabled or unaccepted sandbox costs nothing.
"""
from __future__ import annotations

import logging
from functools import lru_cache

from nexus_core.deployment import DeploymentConfigError
from nexus_sandbox.manager import SandboxManager
from nexus_sandbox.settings import load_settings

logger = logging.getLogger("nexus_worker.sandbox")


@lru_cache(maxsize=1)
def manager() -> SandboxManager | None:
    """The shared manager, or None when the sandbox is disabled or misconfigured."""
    try:
        settings = load_settings()
    except DeploymentConfigError:
        logger.error("Invalid [sandbox] configuration; the sandbox stays off")
        return None
    return SandboxManager(settings) if settings.enabled else None


def session_for(tenant_id: str, session_id: str, *, default_timeout: float, output_limit: int):
    """A sandbox session for this Run, or None when no sandbox is available."""
    current = manager()
    if current is None:
        return None
    return current.session(tenant_id, session_id, default_timeout=default_timeout, output_limit=output_limit)


async def reap_idle() -> None:
    """Remove idle and orphaned session containers; called from the worker loop, never raises."""
    current = manager()
    if current is None:
        return
    try:
        removed = await current.reap()
        if removed:
            logger.info("Removed %d idle sandbox container(s)", len(removed))
    except Exception:
        logger.warning("Sandbox reclamation failed", exc_info=True)
