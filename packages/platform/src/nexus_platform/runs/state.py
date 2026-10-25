"""Run state: one application responsibility with legacy function compatibility."""
from __future__ import annotations
from nexus_core.platform import RunStatus
from nexus_platform.errors import Conflict
from typing import Protocol


class RunState(Protocol):
    """Mutable state shared by domain Runs and the legacy persistence adapter."""
    status: str


ALLOWED_TRANSITIONS = {
    RunStatus.QUEUED: {RunStatus.RUNNING, RunStatus.FAILED, RunStatus.CANCELLED, RunStatus.INTERRUPTED},
    RunStatus.RUNNING: {
        RunStatus.WAITING_INPUT, RunStatus.WAITING_APPROVAL, RunStatus.COMPLETED,
        RunStatus.FAILED, RunStatus.CANCELLED, RunStatus.INTERRUPTED,
    },
    RunStatus.WAITING_INPUT: {RunStatus.RUNNING, RunStatus.FAILED, RunStatus.CANCELLED, RunStatus.INTERRUPTED},
    RunStatus.WAITING_APPROVAL: {RunStatus.RUNNING, RunStatus.FAILED, RunStatus.CANCELLED, RunStatus.INTERRUPTED},
}


def transition_run(run: RunState, target: RunStatus) -> None:
    """Apply a legal transition in place; identical status is a no-op, invalid edges conflict."""
    current = RunStatus(run.status)
    if target == current:
        return
    if target not in ALLOWED_TRANSITIONS.get(current, set()):
        raise Conflict(f"Run cannot transition from {current.value} to {target.value}")
    run.status = target.value
