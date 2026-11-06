from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from nexus_core.platform import Principal, new_id, utc_now
from nexus_platform.errors import Conflict, InvalidConfiguration, NotFound
from nexus_platform.identity.service import require_membership, require_tenant, resolve_user
from nexus_platform.models.service import clean_public_options, content_hash
from nexus_platform.models.provider_settings import authorize_model
from nexus_platform.persistence.models import (
    SkillVersionRecord,
    AgentDraftBindingRecord,
    AgentRecord,
    AgentVersionRecord,
    CredentialReferenceRecord,
    ModelProfileRecord,
    ModelProfileVersionRecord,
    ResourceBindingRecord,
)
from nexus_platform.agents.access import require_agent_permission
from nexus_platform.authz.permissions import require_api_permission
from nexus_platform.authz.audit import audit
from nexus_platform.authz.resources import authorize_resource
from nexus_platform.agents.generation import validate_generation
from nexus_memory.switches import validate_agent_budget as validate_memory_budget


#: Soft-deleted agents (proposal 2026-11-05 decision 2): hidden, not editable, cannot start Runs.
ARCHIVED = "archived"


def create_agent(
    session: Session,
    principal: Principal,
    tenant_id: UUID,
    *,
    name: str,
    description: str,
    runtime_type: str,
    instructions: str,
    model_profile_version_id: UUID,
    budgets: dict[str, Any],
    bindings: list[dict[str, Any]],
) -> AgentRecord:
    now = utc_now()
    clean_public_options(budgets, "budgets")
    validate_generation(budgets)
    validate_memory_budget(budgets)
    clean_public_options(instructions, "instructions")
    clean_public_options(description, "description")
    name = name.strip()
    if not name or not runtime_type.strip():
        raise ValueError("Agent name and runtime type must not be empty")
    with session.begin():
        user = resolve_user(session, principal)
        require_tenant(session, tenant_id)
        require_membership(session, tenant_id, user.id)
        require_api_permission(session, tenant_id, user.id, "agents:write")
        verify_model_version(session, tenant_id, model_profile_version_id)
        authorize_model(session, tenant_id, user.id, model_profile_version_id)
        agent = AgentRecord(
            id=new_id(), tenant_id=tenant_id, name=name.strip(), description=description.strip(),
            status="draft", draft_runtime_type=runtime_type, draft_instructions=instructions,
            draft_model_profile_version_id=model_profile_version_id, draft_budgets=budgets,
            published_version_id=None, version_counter=0, created_by=user.id, created_at=now, updated_at=now,
        )
        session.add(agent)
        session.flush()
        replace_draft_bindings(session, agent, bindings)
        audit(session, tenant_id, user.id, "agent.created", "agent", str(agent.id))
    return agent


def update_agent_draft(
    session: Session,
    principal: Principal,
    tenant_id: UUID,
    agent_id: UUID,
    *,
    name: str,
    description: str,
    runtime_type: str,
    instructions: str,
    model_profile_version_id: UUID,
    budgets: dict[str, Any],
    bindings: list[dict[str, Any]],
) -> AgentRecord:
    now = utc_now()
    clean_public_options(budgets, "budgets")
    validate_generation(budgets)
    validate_memory_budget(budgets)
    clean_public_options(instructions, "instructions")
    clean_public_options(description, "description")
    name = name.strip()
    if not name or not runtime_type.strip():
        raise ValueError("Agent name and runtime type must not be empty")
    with session.begin():
        user = resolve_user(session, principal)
        require_tenant(session, tenant_id)
        require_membership(session, tenant_id, user.id)
        agent = session.scalar(
            select(AgentRecord).where(
                AgentRecord.id == agent_id, AgentRecord.tenant_id == tenant_id
            ).with_for_update()
        )
        if agent is None or agent.status == ARCHIVED:
            raise NotFound("Agent not found")
        require_agent_permission(session, tenant_id, user.id, agent, "edit")
        verify_model_version(session, tenant_id, model_profile_version_id)
        authorize_model(session, tenant_id, user.id, model_profile_version_id)
        agent.name = name.strip()
        agent.description = description.strip()
        agent.draft_runtime_type = runtime_type
        agent.draft_instructions = instructions
        agent.draft_model_profile_version_id = model_profile_version_id
        agent.draft_budgets = budgets
        agent.status = "draft"
        agent.updated_at = now
        replace_draft_bindings(session, agent, bindings)
        audit(session, tenant_id, user.id, "agent.draft_updated", "agent", str(agent.id))
    return agent


def publish_agent(session: Session, principal: Principal, tenant_id: UUID, agent_id: UUID) -> AgentVersionRecord:
    now = utc_now()
    with session.begin():
        user = resolve_user(session, principal)
        require_tenant(session, tenant_id)
        require_membership(session, tenant_id, user.id)
        agent = session.scalar(
            select(AgentRecord).where(
                AgentRecord.id == agent_id, AgentRecord.tenant_id == tenant_id
            ).with_for_update()
        )
        if agent is None or agent.status == ARCHIVED:
            raise NotFound("Agent not found")
        require_agent_permission(session, tenant_id, user.id, agent, "publish")
        if agent.draft_runtime_type != "native":
            raise InvalidConfiguration("Only native configuration is supported in P1")
        if not agent.draft_model_profile_version_id:
            raise InvalidConfiguration("Agent must reference a model profile version")
        model_profile, model_version = verify_model_version(
            session, tenant_id, agent.draft_model_profile_version_id
        )
        authorize_model(session, tenant_id, user.id, model_version.id)
        # Native behavior is snapshotted at publish: validate it here, and recheck the
        # compaction model's grant, so an invalid or unauthorized setting cannot be published.
        behavior = (agent.draft_budgets or {}).get("behavior")
        if isinstance(behavior, dict):
            from nexus_core.native import NativePolicy
            try:
                policy = NativePolicy(**behavior)
            except (TypeError, ValueError) as exc:
                raise InvalidConfiguration(f"Native behavior settings are invalid: {exc}") from None
            if policy.compaction_model_profile_version_id:
                authorize_model(session, tenant_id, user.id, UUID(policy.compaction_model_profile_version_id))
        if model_version.credential_reference_id:
            credential = session.get(CredentialReferenceRecord, model_version.credential_reference_id)
            if credential is None or credential.tenant_id != tenant_id or credential.status != "active":
                raise InvalidConfiguration("Credential reference is unavailable")
        draft_bindings = list(
            session.scalars(
                select(AgentDraftBindingRecord).where(AgentDraftBindingRecord.agent_id == agent.id)
            )
        )
        for binding in draft_bindings:
            authorize_resource(
                session, tenant_id, binding.kind, binding.resource_id,
                source_tenant_id=binding.source_tenant_id,
                resource_version_id=binding.resource_version_id, permission="use"
            )
        check_skill_dependencies(session, tenant_id, draft_bindings)
        check_knowledge_dependencies(draft_bindings)
        version_number = agent.version_counter + 1
        snapshot = {
            "agent_id": str(agent.id), "version": version_number, "name": agent.name,
            "description": agent.description, "runtime_type": agent.draft_runtime_type,
            "instructions": agent.draft_instructions, "model_profile_id": str(model_profile.id),
            "model_profile_version_id": str(model_version.id), "budgets": agent.draft_budgets,
            "bindings": [binding_snapshot(row) for row in draft_bindings],
        }
        version = AgentVersionRecord(
            id=new_id(), agent_id=agent.id, tenant_id=tenant_id,
            version=version_number, name=agent.name, description=agent.description,
            runtime_type=agent.draft_runtime_type,
            instructions=agent.draft_instructions, model_profile_version_id=model_version.id,
            budgets=agent.draft_budgets, content_hash=content_hash(snapshot), created_by=user.id,
            published_at=now,
        )
        session.add(version)
        session.flush()
        for binding in draft_bindings:
            session.add(
                ResourceBindingRecord(
                    id=new_id(), agent_version_id=version.id, kind=binding.kind,
                    resource_id=binding.resource_id, resource_version_id=binding.resource_version_id,
                    source_tenant_id=binding.source_tenant_id,
                    binding_config=clean_public_options(binding.binding_config, "binding_config"),
                )
            )
        agent.version_counter = version_number
        agent.published_version_id = version.id
        agent.status = "published"
        agent.updated_at = now
        audit(session, tenant_id, user.id, "agent.published", "agent_version", str(version.id),
              {"agent_id": str(agent.id), "version": version_number, "content_hash": version.content_hash})
    return version


def get_agent(session: Session, tenant_id: UUID, agent_id: UUID):
    """Return a non-archived agent and its draft bindings; archived agents report NotFound."""
    agent = session.scalar(
        select(AgentRecord).where(AgentRecord.id == agent_id, AgentRecord.tenant_id == tenant_id)
    )
    if agent is None or agent.status == ARCHIVED:
        raise NotFound("Agent not found")
    draft_bindings = list(
        session.scalars(select(AgentDraftBindingRecord).where(AgentDraftBindingRecord.agent_id == agent.id))
    )
    return agent, draft_bindings


def list_all_agents_for_platform_admin(session: Session, principal: Principal) -> list[AgentRecord]:
    """Every agent across spaces, for the platform administrator's session filter. Others get Forbidden."""
    from nexus_platform.errors import Forbidden
    from nexus_platform.identity.service import resolve_user
    with session.begin():
        if not resolve_user(session, principal).is_platform_admin:
            raise Forbidden("Platform administrator required")
        return list(session.scalars(select(AgentRecord).order_by(AgentRecord.tenant_id, AgentRecord.name)))


def list_agents(session: Session, tenant_id: UUID) -> list[AgentRecord]:
    """List the space's agents in creation order, excluding archived ones."""
    return list(
        session.scalars(
            select(AgentRecord).where(
                AgentRecord.tenant_id == tenant_id, AgentRecord.status != ARCHIVED
            ).order_by(AgentRecord.created_at)
        )
    )


def archive_agent(session: Session, principal: Principal, tenant_id: UUID, agent_id: UUID) -> None:
    """Soft-delete an agent (reference: WeKnora agent deletion; Nexus keeps history).

    Requires ``agents:write`` and the agent's ``manage`` permission. The agent disappears from lists
    and new sessions; existing sessions keep their messages but cannot submit new Runs. Published
    versions and bindings are retained so past Runs stay auditable.
    """
    with session.begin():
        user = resolve_user(session, principal)
        require_tenant(session, tenant_id)
        require_membership(session, tenant_id, user.id)
        agent = session.scalar(
            select(AgentRecord).where(
                AgentRecord.id == agent_id, AgentRecord.tenant_id == tenant_id
            ).with_for_update()
        )
        if agent is None or agent.status == ARCHIVED:
            raise NotFound("Agent not found")
        require_agent_permission(session, tenant_id, user.id, agent, "manage")
        require_api_permission(session, tenant_id, user.id, "agents:write")
        agent.status = ARCHIVED
        agent.updated_at = utc_now()
        audit(session, tenant_id, user.id, "agent.archived", "agent", str(agent.id))


def copy_agent(session: Session, principal: Principal, tenant_id: UUID, agent_id: UUID, *, name: str) -> AgentRecord:
    """Copy an agent's draft into a new, unpublished agent owned by the caller.

    Shares, grants and published versions are not copied. Every binding and the model are
    re-authorized for the caller, so a copy never widens access.
    """
    with session.begin():
        user = resolve_user(session, principal)
        require_tenant(session, tenant_id)
        require_membership(session, tenant_id, user.id)
        source = session.scalar(
            select(AgentRecord).where(AgentRecord.id == agent_id, AgentRecord.tenant_id == tenant_id)
        )
        if source is None or source.status == ARCHIVED:
            raise NotFound("Agent not found")
        require_agent_permission(session, tenant_id, user.id, source, "edit")
        bindings = [binding_snapshot(row) for row in session.scalars(
            select(AgentDraftBindingRecord).where(AgentDraftBindingRecord.agent_id == source.id)
        )]
        model_id = source.draft_model_profile_version_id
        runtime_type, instructions = source.draft_runtime_type, source.draft_instructions
        description, budgets = source.description, dict(source.draft_budgets or {})
    for binding in bindings:
        binding["source_tenant_id"] = UUID(binding["source_tenant_id"])
    if model_id is None:
        raise InvalidConfiguration("Agent must reference a model profile version")
    return create_agent(
        session, principal, tenant_id, name=name[:160], description=description, runtime_type=runtime_type,
        instructions=instructions, model_profile_version_id=model_id, budgets=budgets, bindings=bindings,
    )


def verify_model_version(session: Session, tenant_id: UUID, version_id: UUID):
    row = session.execute(
        select(ModelProfileRecord, ModelProfileVersionRecord)
        .join(ModelProfileVersionRecord, ModelProfileVersionRecord.profile_id == ModelProfileRecord.id)
        .where(
            ModelProfileRecord.tenant_id == tenant_id,
            ModelProfileVersionRecord.id == version_id,
        )
    ).first()
    if row is None:
        raise NotFound("Model profile version not found")
    return row[0], row[1]


def replace_draft_bindings(session: Session, agent: AgentRecord, bindings: list[dict[str, Any]]) -> None:
    session.query(AgentDraftBindingRecord).filter(AgentDraftBindingRecord.agent_id == agent.id).delete(
        synchronize_session=False
    )
    seen: set[tuple[str, str, str, str]] = set()
    for raw in bindings:
        kind = str(raw["kind"]).strip()
        resource_id = str(raw["resource_id"]).strip()
        source_tenant_id = UUID(str(raw["source_tenant_id"]))
        version_id = str(raw.get("resource_version_id") or "")
        key = (kind, resource_id, version_id, str(source_tenant_id))
        if key in seen:
            raise Conflict("Duplicate agent resource binding")
        seen.add(key)
        session.add(
            AgentDraftBindingRecord(
                id=new_id(), agent_id=agent.id, kind=kind, resource_id=resource_id,
                resource_version_id=version_id, source_tenant_id=source_tenant_id,
                binding_config=clean_public_options(raw.get("config", {}), "binding_config"),
            )
        )


def check_skill_dependencies(session: Session, tenant_id: UUID, bindings: list[AgentDraftBindingRecord]) -> None:
    """Refuse to publish when a bound skill needs a tool this agent does not bind (proposal 4.3).

    Skills that load and read skill files need ``load_skill`` and ``read_skill_file``; each skill's
    declared ``tools`` must also be bound. Missing dependencies are reported by name.
    """
    skill_rows = [binding for binding in bindings if binding.kind == "skill"]
    if not skill_rows:
        return
    bound_tools = {binding.resource_id for binding in bindings if binding.kind == "tool"}
    for needed in ("load_skill", "read_skill_file"):
        if needed not in bound_tools:
            raise InvalidConfiguration(f"skill_dependency_missing:{needed}")
    for binding in skill_rows:
        try:
            version = session.get(SkillVersionRecord, UUID(binding.resource_version_id))
        except ValueError:
            version = None
        if version is None or version.tenant_id != binding.source_tenant_id:
            raise InvalidConfiguration("skill_unavailable")
        for tool in version.tools:
            if tool not in bound_tools:
                raise InvalidConfiguration(f"skill_dependency_missing:{tool}")


def check_knowledge_dependencies(bindings: list[AgentDraftBindingRecord]) -> None:
    """An agent that binds knowledge bases must bind ``search_knowledge`` (openspec 2026-11-06-knowledge-base).

    The editor selects the knowledge tools together with the first knowledge base; this keeps a published
    version from binding bases it can never search.
    """
    if any(binding.kind == "knowledge_base" for binding in bindings) and not any(
            binding.kind == "tool" and binding.resource_id == "search_knowledge" for binding in bindings):
        raise InvalidConfiguration("knowledge_dependency_missing:search_knowledge")


def binding_snapshot(binding: AgentDraftBindingRecord | ResourceBindingRecord) -> dict[str, Any]:
    return {
        "kind": binding.kind,
        "resource_id": binding.resource_id,
        "resource_version_id": binding.resource_version_id or None,
        "source_tenant_id": str(binding.source_tenant_id),
        "config": binding.binding_config,
    }
