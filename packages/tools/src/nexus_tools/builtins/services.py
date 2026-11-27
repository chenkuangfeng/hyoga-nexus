"""Access to the Run-scoped services that shared builtin tools need."""
import asyncio
from nexus_core.runtime import RuntimeFault


class RunServices:
    """The Run's store plus the Run's mutable progress state, handed to builtin handlers.

    Store methods are forwarded by attribute access, so existing handlers keep calling the store
    directly. `run_state` is the same dict as `RuntimeProgress.state`: it persists with progress and
    is released when the Run ends.
    """

    def __init__(self, store, run_state: dict, sandbox=None, delegate=None, vision=None, schedule=None):
        self._store = store
        self.run_state = run_state
        #: The Run's `SandboxSessionPort`, supplied only while the `sandbox` tool group is offered.
        self.sandbox = sandbox
        #: The Run's sub-agent runner (`delegate_task`), supplied only while the `collab` group is offered.
        self.delegate = delegate
        #: Image analyzer for `vision_analyze` (`async analyze(image, mime, question) -> str`), when a vision model is set.
        self.vision = vision
        #: Scheduled-task service for `cronjob_*` (`async list/create/change`), while the `schedule` group is offered.
        self.schedule = schedule

    def __getattr__(self, name):
        return getattr(self._store, name)

    async def skill_manage(self, action: str, arguments: dict):
        """Apply a private draft edit to the database, then refresh its user-workspace mirror."""
        result = await self._store.skill_manage(action, arguments)
        sync = getattr(self.sandbox, 'sync_skill_draft', None)
        if sync is not None:
            files = result.pop('_workspace_files', None)
            name = result.get('name', arguments.get('name', ''))
            try:
                await asyncio.to_thread(sync, name, None if action == 'delete_draft' else files)
            except Exception:
                # This is a rebuildable cache. The committed database draft remains the source of truth.
                pass
        return result

    async def skill_save(self, name: str):
        """Save through the existing database approval flow and remove the now-consumed draft mirror."""
        result = await self._store.skill_save(name)
        sync = getattr(self.sandbox, 'sync_skill_draft', None)
        if sync is not None:
            try:
                await asyncio.to_thread(sync, name, None)
            except Exception:
                pass
        return result


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


def run_state_of(context) -> dict:
    """Return the Run-scoped state dict, or fail closed when the composition root did not supply one."""
    state = getattr(store_of(context), 'run_state', None)
    if not isinstance(state, dict):
        raise RuntimeFault('tool_unavailable')
    return state


def sandbox_of(context):
    """Return the Run's sandbox session, or fail closed when none was wired (group off or backend missing)."""
    sandbox = getattr(store_of(context), 'sandbox', None)
    if sandbox is None:
        raise RuntimeFault('tool_unavailable')
    return sandbox
