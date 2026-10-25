"""Run submission: one application responsibility with legacy function compatibility."""
from __future__ import annotations
from nexus_platform.persistence.unit_of_work import SqlAlchemyUnitOfWork
from typing import Any
from uuid import UUID
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from nexus_core.platform import Principal, RunStatus, new_id, utc_now
from nexus_platform.errors import Conflict, Forbidden, NotFound
from nexus_platform.models.provider_settings import authorize_model
from nexus_platform.identity.service import require_membership, require_workspace, resolve_user
from nexus_platform.persistence.models import (
    AgentRecord,
    AgentVersionRecord,
    MessageRecord,
    ModelProfileRecord,
    ModelProfileVersionRecord,
    OutboxRecord,
    ResourceBindingRecord,
    RunRecord,
    SessionRecord,
)
from nexus_platform.workspaces.service import audit, authorize_resource
from .events import append_event
from .hashing import digest

def create_run(session: Session, principal: Principal, workspace_id: UUID, session_id: UUID, *, message: str, idempotency_key: str) -> tuple[RunRecord, bool]:
    return RunSubmissionService(SqlAlchemyUnitOfWork(session)).submit(principal, workspace_id, session_id, message=message, idempotency_key=idempotency_key)

class RunSubmissionService:
    """Own the submission application operation and its transaction boundary."""

    def __init__(self, unit_of_work: SqlAlchemyUnitOfWork):
        self.unit_of_work = unit_of_work

    def submit(
        self,
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
        with self.unit_of_work as work:
            session = work.session
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
            authorize_model(session, workspace_id, user.id, agent_version.model_profile_version_id)
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

            if session.scalar(select(RunRecord.id).where(
                RunRecord.session_id == session_id,
                RunRecord.status.in_(['queued', 'running', 'waiting_input', 'waiting_approval']),
            ).limit(1)) is not None:
                raise Conflict("Session already has an active Run")

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
