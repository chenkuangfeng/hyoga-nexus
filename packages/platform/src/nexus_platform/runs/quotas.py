"""Fairness limits on active sessions, in addition to the deployment-wide cap (openspec 2026-11-07-run-event-streaming).

``[platform].max_concurrent_sessions_per_tenant`` and ``..._per_user`` bound how many distinct sessions one
tenant or one user may have holding queued, started or unknown work. Both are off unless set, so an existing
deployment behaves as before. The deployment-wide cap (``max_concurrent_sessions``) is unchanged.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from nexus_core.deployment import CONFIG_RELATIVE_PATH, DeploymentConfigError, section

_FILE = CONFIG_RELATIVE_PATH.as_posix()


@dataclass(frozen=True)
class SessionQuotas:
    """Per-tenant and per-user active-session limits; ``None`` means unlimited."""

    per_tenant: int | None = None
    per_user: int | None = None


def session_quotas(path: Path | None = None) -> SessionQuotas:
    """Read the limits from ``[platform]``; a non-positive or non-integer value stops start-up."""
    table = section("platform", path)
    values = {}
    for key, field in (("max_concurrent_sessions_per_tenant", "per_tenant"), ("max_concurrent_sessions_per_user", "per_user")):
        value = table.get(key)
        if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 1):
            raise DeploymentConfigError(f"{_FILE} [platform].{key} must be a positive integer")
        values[field] = value
    return SessionQuotas(**values)
