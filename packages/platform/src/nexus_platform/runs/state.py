"""Run state: one application responsibility with legacy function compatibility."""
from __future__ import annotations
from nexus_core.platform import RunStatus
from nexus_platform.errors import Conflict
from nexus_platform.persistence.models import RunRecord


ALLOWED_TRANSITIONS = {
    RunStatus.QUEUED: {RunStatus.RUNNING, RunStatus.FAILED, RunStatus.CANCELLED, RunStatus.INTERRUPTED},
    RunStatus.RUNNING: {
        RunStatus.WAITING_INPUT, RunStatus.WAITING_APPROVAL, RunStatus.COMPLETED,
        RunStatus.FAILED, RunStatus.CANCELLED, RunStatus.INTERRUPTED,
    },
    RunStatus.WAITING_INPUT: {RunStatus.RUNNING, RunStatus.FAILED, RunStatus.CANCELLED, RunStatus.INTERRUPTED},
    RunStatus.WAITING_APPROVAL: {RunStatus.RUNNING, RunStatus.FAILED, RunStatus.CANCELLED, RunStatus.INTERRUPTED},
}


def transition_run(run: RunRecord, target: RunStatus) -> None:
    current = RunStatus(run.status)
    if target == current:
        return
    if target not in ALLOWED_TRANSITIONS.get(current, set()):
        raise Conflict(f"Run cannot transition from {current.value} to {target.value}")
    run.status = target.value
