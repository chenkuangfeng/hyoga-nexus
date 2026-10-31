"""Run submission policy and orchestration, independent of SQLAlchemy and HTTP."""
from uuid import UUID

from nexus_core.platform import Principal, RunStatus, new_id, utc_now
from nexus_platform.errors import Conflict, Forbidden, NotFound
from .command_ports import RunCommandUnitOfWork
from .domain import Run
from .hashing import digest


class RunSubmissionService:
    """Authorize, freeze configuration and submit all initial Run writes atomically."""
    def __init__(self, unit_of_work: RunCommandUnitOfWork):
        self.unit_of_work = unit_of_work

    @staticmethod
    def _replay(existing: Run, request_hash: str) -> tuple[Run, bool]:
        if existing.request_hash != request_hash:
            raise Conflict("Idempotency key was already used for a different request")
        return existing, True

    def submit(self, principal: Principal, tenant_id: UUID, session_id: UUID, *,
               message: str, idempotency_key: str) -> tuple[Run, bool]:
        """Submit or replay after current authorization, preserving the Session's fixed version.

        Invalid keys raise ValueError; invisible resources raise NotFound/Forbidden and
        conflicting keys or active Runs raise Conflict. Any write failure rolls back the
        configuration, message, event, delivery and audit in this single UnitOfWork.
        """
        idempotency_key = idempotency_key.strip()
        if not idempotency_key or len(idempotency_key) > 255:
            raise ValueError("Idempotency-Key must contain 1 to 255 characters")
        now = utc_now()
        with self.unit_of_work as work:
            member = work.access.require_member(principal, tenant_id)
            session = work.catalog.owned_session(tenant_id, member.user_id, session_id)
            if session is None:
                raise NotFound("Session not found")
            if session.status != "active":
                raise Conflict("Session is not active")
            agent = work.catalog.agent_version(session.agent_version_id)
            if agent is None:
                raise Conflict("Session agent version is unavailable")
            if work.catalog.agent_tenant(agent.agent_id) != tenant_id:
                raise NotFound("Session not found")
            bindings = work.catalog.bindings(agent.id)
            for binding in bindings:
                work.access.require_resource(tenant_id, binding)
            work.access.require_agent_run(tenant_id, member.user_id, agent.agent_id)
            work.access.require_model(tenant_id, member.user_id, agent.model_profile_version_id)
            model = work.catalog.model_version(agent.model_profile_version_id)
            if model is None:
                raise Conflict("Agent model profile version is unavailable")
            if work.catalog.model_tenant(model.profile_id) != tenant_id:
                raise Forbidden("Model profile is not available in this tenant")

            # A replay never bypasses the current membership, model or resource checks.
            request_hash = digest({"session_id": str(session_id), "message": message})
            existing = work.runs.by_key(tenant_id, member.user_id, idempotency_key)
            if existing is not None:
                return self._replay(existing, request_hash)
            if work.runs.has_active(session_id):
                raise Conflict("Session already has an active Run")
            config_snapshot = {
                "agent_id": str(agent.agent_id),
                "agent_version_id": str(agent.id),
                "agent_version": agent.version,
                "agent_content_hash": agent.content_hash,
                "runtime_type": agent.runtime_type,
                "model_profile_id": str(model.profile_id),
                "model_profile_version_id": str(model.id),
                "model_profile_content_hash": model.content_hash,
                "credential_reference_id": str(model.credential_reference_id)
                if model.credential_reference_id else None,
                "budgets": agent.budgets,
                "resources": [binding.snapshot() for binding in bindings],
                "principal_id": str(member.user_id),
                "membership_role": member.role,
                "authorized_at": now.isoformat(),
            }
            candidate = Run(
                id=new_id(), tenant_id=tenant_id, session_id=session_id,
                principal_id=member.user_id, status=RunStatus.QUEUED.value,
                idempotency_key=idempotency_key, request_hash=request_hash,
                config_snapshot=config_snapshot, created_at=now,
            )
            run, inserted = work.runs.insert_or_replay(candidate)
            if not inserted:
                return self._replay(run, request_hash)
            work.messages.initial(run, message, now)
            work.events.append(run.id, "run.queued", {"status": RunStatus.QUEUED.value}, now)
            work.outbox.enqueue(run.id, "run.execute", now)
            work.catalog.touch_session(session_id, now)
            work.audit.write(tenant_id, member.user_id, "run.created", "run", str(run.id),
                             {"session_id": str(session_id), "agent_version_id": str(agent.id)})
        return run, False


# Legacy import only. The compatibility module owns all mapped-entity conversion.
from .compatibility import create_run
