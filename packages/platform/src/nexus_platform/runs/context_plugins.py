"""Process-local registrations of trusted plugin generations for durable source checks.

Only worker composition registers these; no HTTP or model argument can enable a generation.
A process restart requires plugins to be loaded again. Contains identities, no plugin text.
"""
from __future__ import annotations
import threading

_lock = threading.Lock()
_generations: dict[str, str] = {}


def register_plugin_generation(name: str, generation: str) -> None:
    """Publish a trusted implementation generation during application startup."""
    with _lock:
        _generations[name] = generation


def unregister_plugin_generation(name: str) -> None:
    """Revoke a registration; its existing content fails the next request gate."""
    with _lock:
        _generations.pop(name, None)


def plugin_dependencies_allowed(dependencies) -> bool:
    """Check only registered generations; tenant/principal checks remain in the Run gate."""
    with _lock:
        return all(_generations.get(d.resource_id) == d.version for d in dependencies)
