"""Worker side of artifact registration (openspec 2026-11-07-tool-expansion 4.6).

When a Run ends, the files it left under `/outputs` are copied and recorded by `nexus_platform.artifacts`. This runs
for every ending (completed, failed, cancelled) because a partial result is still worth keeping, and it never raises:
a failure to register is logged and the Run keeps the outcome it had.
"""
from __future__ import annotations

import logging

from nexus_platform.artifacts import service

logger = logging.getLogger("nexus_worker.artifacts")


def register_outputs(factory, context, sandbox) -> int:
    """Register the Run's `/outputs` files; returns how many were registered. Blocking: call it through `run_db`."""
    try:
        files = sandbox.output_files()
        if not files:
            return 0
        with factory() as db:
            result = service.register_run_outputs(
                db, tenant_id=context.tenant_id, session_id=context.session_id, run_id=context.run_id,
                owner_user_id=context.principal_id, files=files)
        return len(result['registered'])
    except Exception:
        logger.warning("Artifact registration failed for run %s", getattr(context, 'run_id', '?'), exc_info=True)
        return 0
