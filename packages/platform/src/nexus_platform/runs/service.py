from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from nexus_core.platform import Principal, RunStatus, new_id, utc_now
from nexus_platform.errors import Conflict, Forbidden, NotFound
from nexus_platform.identity.service import require_membership, require_workspace, resolve_user
from nexus_platform.persistence.models import (
    AgentRecord,
    AgentVersionRecord,
    MessageRecord,
    ModelProfileRecord,
    ModelProfileVersionRecord,
    OutboxRecord,
    ResourceBindingRecord,
    RunEventRecord,
    RunRecord,
    SessionRecord,
)
from nexus_platform.workspaces.service import audit, authorize_resource

DEFAULT_LEASE_SECONDS = 60
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


def create_run(
    session: Session,
    principal: Principal,
    workspace_id: UUID,
    session_id: UUID,
    *,
    message: str,
    idempotency_key: str,
) -> tuple[RunRecord, bool]:
    idempotency_key = idempotency_key.strip()
    if not idempotency_key or len(idempotency_key) > 255:
        raise ValueError("Idempotency-Key must contain 1 to 255 characters")
    now = utc_now()
    with session.begin():
        user = resolve_user(session, principal)
        require_workspace(session, workspace_id)
        membership = require_membership(session, workspace_id, user.id)
        session_row = session.scalar(
            select(SessionRecord).where(
                SessionRecord.id == session_id,
                SessionRecord.workspace_id == workspace_id,
                SessionRecord.owner_user_id == user.id,
            ).with_for_update()
        )
        if session_row is None:
            raise NotFound("Session not found")
        if session_row.status != "active":
            raise Conflict("Session is not active")
        agent_version = session.get(AgentVersionRecord, session_row.agent_version_id)
        if agent_version is None:
            raise Conflict("Session agent version is unavailable")
        agent = session.get(AgentRecord, agent_version.agent_id)
        if agent is None or agent.workspace_id != workspace_id:
            raise NotFound("Session not found")
        bindings = list(
            session.scalars(
                select(ResourceBindingRecord).where(
                    ResourceBindingRecord.agent_version_id == agent_version.id
                )
            )
        )
        for binding in bindings:
            authorize_resource(
                session, workspace_id, binding.kind, binding.resource_id,
                source_workspace_id=binding.source_workspace_id,
                resource_version_id=binding.resource_version_id, permission="use"
            )
        profile_version = session.get(ModelProfileVersionRecord, agent_version.model_profile_version_id)
        if profile_version is None:
            raise Conflict("Agent model profile version is unavailable")
        profile = session.get(ModelProfileRecord, profile_version.profile_id)
        if profile is None or profile.workspace_id != workspace_id:
            raise Forbidden("Model profile is not available in this workspace")

        request_hash = digest({"session_id": str(session_id), "message": message})
        existing = session.scalar(
            select(RunRecord).where(
                RunRecord.workspace_id == workspace_id,
                RunRecord.principal_id == user.id,
                RunRecord.idempotency_key == idempotency_key,
            )
        )
        if existing is not None:
            if existing.request_hash != request_hash:
                raise Conflict("Idempotency key was already used for a different request")
            return existing, True

        authorized_resources: list[dict[str, Any]] = []
        for binding in bindings:
            authorized_resources.append({
                "kind": binding.kind,
                "resource_id": binding.resource_id,
                "resource_version_id": binding.resource_version_id or None,
                "source_workspace_id": str(binding.source_workspace_id),
                "binding_id": str(binding.id),
                "config": binding.binding_config,
            })
        config_snapshot = {
            "agent_id": str(agent.id),
            "agent_version_id": str(agent_version.id),
            "agent_version": agent_version.version,
            "agent_content_hash": agent_version.content_hash,
            "runtime_type": agent_version.runtime_type,
            "model_profile_id": str(profile.id),
            "model_profile_version_id": str(profile_version.id),
            "model_profile_content_hash": profile_version.content_hash,
            "credential_reference_id": str(profile_version.credential_reference_id)
            if profile_version.credential_reference_id else None,
            "budgets": agent_version.budgets,
            "resources": authorized_resources,
            "principal_id": str(user.id),
            "membership_role": membership.role,
            "authorized_at": now.isoformat(),
        }
        run = RunRecord(
            id=new_id(), workspace_id=workspace_id, session_id=session_id, principal_id=user.id,
            status=RunStatus.QUEUED.value, idempotency_key=idempotency_key, request_hash=request_hash,
            config_snapshot=config_snapshot, attempt=0, lease_owner=None, lease_until=None,
            cancel_requested_at=None, error_code=None, error_message=None, created_at=now,
        )
        try:
            with session.begin_nested():
                session.add(run)
                session.flush()
        except IntegrityError:
            existing = session.scalar(
                select(RunRecord).where(
                    RunRecord.workspace_id == workspace_id,
                    RunRecord.principal_id == user.id,
                    RunRecord.idempotency_key == idempotency_key,
                )
            )
            if existing is None:
                raise
            if existing.request_hash != request_hash:
                raise Conflict("Idempotency key was already used for a different request")
            return existing, True
        message_sequence = session.scalar(
            select(func.coalesce(func.max(MessageRecord.sequence), 0)).where(
                MessageRecord.session_id == session_id
            )
        ) + 1
        session.add(
            MessageRecord(
                id=new_id(), session_id=session_id, run_id=run.id, sequence=message_sequence,
                role="user", content=message, created_at=now,
            )
        )
        append_event(session, run.id, "run.queued", {"status": RunStatus.QUEUED.value}, now)
        session.add(
            OutboxRecord(
                id=new_id(), run_id=run.id, message_type="run.execute", payload={"run_id": str(run.id)},
                available_at=now, attempts=0, created_at=now,
            )
        )
        session_row.updated_at = now
        audit(session, workspace_id, user.id, "run.created", "run", str(run.id),
              {"session_id": str(session_id), "agent_version_id": str(agent_version.id)})
    return run, False


def get_run(session: Session, principal: Principal, workspace_id: UUID, run_id: UUID) -> RunRecord:
    with session.begin():
        user = resolve_user(session, principal)
        require_workspace(session, workspace_id)
        require_membership(session, workspace_id, user.id)
        run = session.scalar(
            select(RunRecord)
            .join(SessionRecord, SessionRecord.id == RunRecord.session_id)
            .where(
                RunRecord.id == run_id,
                RunRecord.workspace_id == workspace_id,
                (RunRecord.principal_id == user.id) | (SessionRecord.owner_user_id == user.id),
            )
        )
        if run is None:
            raise NotFound("Run not found")
        return run


def list_events(session: Session, principal: Principal, workspace_id: UUID, run_id: UUID, after_sequence: int):
    with session.begin():
        user = resolve_user(session, principal)
        require_workspace(session, workspace_id)
        require_membership(session, workspace_id, user.id)
        run = session.scalar(
            select(RunRecord)
            .join(SessionRecord, SessionRecord.id == RunRecord.session_id)
            .where(
                RunRecord.id == run_id,
                RunRecord.workspace_id == workspace_id,
                (RunRecord.principal_id == user.id) | (SessionRecord.owner_user_id == user.id),
            )
        )
        if run is None:
            raise NotFound("Run not found")
        return list(
            session.scalars(
                select(RunEventRecord)
                .where(RunEventRecord.run_id == run.id, RunEventRecord.sequence > after_sequence)
                .order_by(RunEventRecord.sequence)
            )
        )


def request_cancel(session: Session, principal: Principal, workspace_id: UUID, run_id: UUID) -> RunRecord:
    now = utc_now()
    with session.begin():
        user = resolve_user(session, principal)
        require_workspace(session, workspace_id)
        require_membership(session, workspace_id, user.id)
        run = session.scalar(
            select(RunRecord).where(
                RunRecord.id == run_id,
                RunRecord.workspace_id == workspace_id,
                RunRecord.principal_id == user.id,
            ).with_for_update()
        )
        if run is None:
            raise NotFound("Run not found")
        if RunStatus(run.status).terminal:
            return run
        if run.status == RunStatus.QUEUED.value:
            transition_run(run, RunStatus.CANCELLED)
            run.cancel_requested_at = now
            run.ended_at = now
            for task in session.scalars(
                select(OutboxRecord).where(OutboxRecord.run_id == run.id, OutboxRecord.completed_at.is_(None))
            ):
                task.completed_at = now
            append_event(session, run.id, "run.cancelled", {"status": run.status}, now)
        else:
            run.cancel_requested_at = now
            existing_cancel = session.scalar(
                select(OutboxRecord).where(
                    OutboxRecord.run_id == run.id,
                    OutboxRecord.message_type == "run.cancel",
                    OutboxRecord.completed_at.is_(None),
                )
            )
            if existing_cancel is None:
                session.add(
                    OutboxRecord(
                        id=new_id(), run_id=run.id, message_type="run.cancel", payload={"run_id": str(run.id)},
                        available_at=now, attempts=0, created_at=now,
                    )
                )
        audit(session, workspace_id, user.id, "run.cancel_requested", "run", str(run.id))
    return run


def claim_next(session: Session, worker_id: str, *, lease_seconds: int = DEFAULT_LEASE_SECONDS) -> UUID | None:
    now = utc_now()
    with session.begin():
        task = session.scalar(
            select(OutboxRecord)
            .where(
                OutboxRecord.completed_at.is_(None),
                OutboxRecord.available_at <= now,
                (OutboxRecord.lease_until.is_(None)) | (OutboxRecord.lease_until <= now),
            )
            .order_by(OutboxRecord.available_at, OutboxRecord.created_at, OutboxRecord.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if task is None:
            return None
        task.lease_owner = worker_id
        task.lease_until = now + timedelta(seconds=lease_seconds)
        task.attempts += 1
        return task.id


def process_claimed(session: Session, task_id: UUID, worker_id: str) -> bool:
    now = utc_now()
    with session.begin():
        task = session.scalar(
            select(OutboxRecord).where(OutboxRecord.id == task_id).with_for_update()
        )
        if task is None or task.completed_at is not None or task.lease_owner != worker_id:
            return False
        run = session.scalar(select(RunRecord).where(RunRecord.id == task.run_id).with_for_update())
        if run is None:
            task.completed_at = now
            return True
        if RunStatus(run.status).terminal:
            task.completed_at = now
            return True
        if task.message_type == "run.cancel" or run.cancel_requested_at is not None:
            transition_run(run, RunStatus.CANCELLED)
            run.ended_at = now
            append_event(session, run.id, "run.cancelled", {"status": run.status}, now)
            audit(session, run.workspace_id, run.principal_id, "run.cancelled", "run", str(run.id))
        elif task.message_type == "run.execute":
            if run.status == RunStatus.RUNNING.value or run.attempt > 0:
                transition_run(run, RunStatus.INTERRUPTED)
                run.error_code = "worker_lease_expired"
                run.error_message = "Worker lost the lease before the run reached a known outcome"
                run.ended_at = now
                append_event(session, run.id, "run.interrupted", {
                    "status": run.status, "error_code": run.error_code,
                }, now)
                audit(session, run.workspace_id, run.principal_id, "run.interrupted", "run", str(run.id),
                      {"error_code": run.error_code})
            else:
                transition_run(run, RunStatus.RUNNING)
                run.attempt += 1
                run.started_at = now
                append_event(session, run.id, "run.started", {"status": run.status}, now)
                transition_run(run, RunStatus.FAILED)
                run.error_code = "runtime_not_configured"
                run.error_message = "P1 persists runs; no runtime executor is configured yet"
                run.ended_at = now
                append_event(session, run.id, "run.failed", {
                    "status": run.status, "error_code": run.error_code,
                }, now)
                audit(session, run.workspace_id, run.principal_id, "run.failed", "run", str(run.id),
                      {"error_code": run.error_code})
        task.completed_at = now
        task.lease_owner = None
        task.lease_until = None
    return True


def append_event(session: Session, run_id: UUID, event_type: str, payload: dict[str, Any], occurred_at=None):
    # The parent run row is locked by callers before allocating a sequence.
    sequence = session.scalar(
        select(func.coalesce(func.max(RunEventRecord.sequence), 0)).where(RunEventRecord.run_id == run_id)
    ) + 1
    event = RunEventRecord(
        id=new_id(), run_id=run_id, sequence=sequence, event_type=event_type, schema_version=1,
        payload=payload, occurred_at=occurred_at or utc_now(),
    )
    session.add(event)
    session.flush()
    return event


def digest(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def authorize_run_resource(
    session: Session,
    principal: Principal,
    workspace_id: UUID,
    run_id: UUID,
    binding_id: UUID,
    *,
    permission: str = "use",
):
    """Permission port for a Runtime/tool adapter; validates the current grant at call time."""
    with session.begin():
        user = resolve_user(session, principal)
        require_workspace(session, workspace_id)
        require_membership(session, workspace_id, user.id)
        run = session.scalar(
            select(RunRecord).where(
                RunRecord.id == run_id,
                RunRecord.workspace_id == workspace_id,
                RunRecord.principal_id == user.id,
            ).with_for_update()
        )
        if run is None:
            raise NotFound("Run not found")
        if run.status != RunStatus.RUNNING.value:
            raise Conflict("Resources may only be accessed while a Run is running")
        binding = session.scalar(
            select(ResourceBindingRecord).where(
                ResourceBindingRecord.id == binding_id,
                ResourceBindingRecord.agent_version_id == UUID(run.config_snapshot["agent_version_id"]),
            )
        )
        if binding is None:
            raise Forbidden("Resource is not bound to this Run")
        resource = authorize_resource(
            session, workspace_id, binding.kind, binding.resource_id,
            source_workspace_id=binding.source_workspace_id,
            resource_version_id=binding.resource_version_id,
            permission=permission,
        )
        audit(session, workspace_id, user.id, "run.resource_access", binding.kind, binding.resource_id,
              {"run_id": str(run.id), "permission": permission})
        return resource
