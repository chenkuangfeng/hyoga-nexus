"""Access to the Run-scoped store that shared builtin tools need."""
from nexus_core.runtime import RuntimeFault


def store_of(context):
    """Return the store supplied for this invocation, or fail closed when none was wired.

    Builtin definitions are process-wide, so they must never fall back to a store captured
    at registration time. A missing store means the composition root did not supply
    ``services``; the call is refused instead of run against the wrong Run.
    """
    services = getattr(context, 'services', None)
    if services is None:
        raise RuntimeFault('tool_unavailable')
    return services
