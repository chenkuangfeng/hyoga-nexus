from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from nexus_core.platform import Principal, new_id, utc_now
from nexus_platform.errors import Conflict, InvalidConfiguration, NotFound
from nexus_platform.identity.service import require_membership, require_workspace, resolve_user
from nexus_platform.models.service import clean_public_options, content_hash
from nexus_platform.models.provider_settings import authorize_model
from nexus_platform.persistence.models import (
    AgentDraftBindingRecord,
    AgentRecord,
    AgentVersionRecord,
    CredentialReferenceRecord,
    ModelProfileRecord,
    ModelProfileVersionRecord,
    ResourceBindingRecord,
)
from nexus_platform.workspaces.service import ADMIN_ROLES
from nexus_platform.authz.audit import audit
from nexus_platform.authz.resources import authorize_resource


def create_agent(
    session: Session,
    principal: Principal,
    workspace_id: UUID,
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
    clean_public_options(instructions, "instructions")
    clean_public_options(description, "description")
    name = name.strip()
    if not name or not runtime_type.strip():
        raise ValueError("Agent name and runtime type must not be empty")
    with session.begin():
        user = resolve_user(session, principal)
        require_workspace(session, workspace_id)
        require_membership(session, workspace_id, user.id)
        verify_model_version(session, workspace_id, model_profile_version_id)
        authorize_model(session, workspace_id, user.id, model_profile_version_id)
        agent = AgentRecord(
            id=new_id(), workspace_id=workspace_id, name=name.strip(), description=description.strip(),
            status="draft", draft_runtime_type=runtime_type, draft_instructions=instructions,
            draft_model_profile_version_id=model_profile_version_id, draft_budgets=budgets,
            published_version_id=None, version_counter=0, created_by=user.id, created_at=now, updated_at=now,
        )
        session.add(agent)
        session.flush()
        replace_draft_bindings(session, agent, bindings)
        audit(session, workspace_id, user.id, "agent.created", "agent", str(agent.id))
    return agent


def update_agent_draft(
    session: Session,
    principal: Principal,
    workspace_id: UUID,
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
    clean_public_options(instructions, "instructions")
    clean_public_options(description, "description")
    name = name.strip()
    if not name or not runtime_type.strip():
        raise ValueError("Agent name and runtime type must not be empty")
    with session.begin():
        user = resolve_user(session, principal)
        require_workspace(session, workspace_id)
        require_membership(session, workspace_id, user.id)
        agent = session.scalar(
            select(AgentRecord).where(
                AgentRecord.id == agent_id, AgentRecord.workspace_id == workspace_id
            ).with_for_update()
        )
        if agent is not None and agent.created_by != user.id:
            require_membership(session, workspace_id, user.id, roles=ADMIN_ROLES)
        if agent is None:
            raise NotFound("Agent not found")
        verify_model_version(session, workspace_id, model_profile_version_id)
        authorize_model(session, workspace_id, user.id, model_profile_version_id)
        agent.name = name.strip()
        agent.description = description.strip()
        agent.draft_runtime_type = runtime_type
        agent.draft_instructions = instructions
        agent.draft_model_profile_version_id = model_profile_version_id
        agent.draft_budgets = budgets
        agent.status = "draft"
        agent.updated_at = now
        replace_draft_bindings(session, agent, bindings)
        audit(session, workspace_id, user.id, "agent.draft_updated", "agent", str(agent.id))
    return agent


def publish_agent(session: Session, principal: Principal, workspace_id: UUID, agent_id: UUID) -> AgentVersionRecord:
    now = utc_now()
    with session.begin():
        user = resolve_user(session, principal)
        require_workspace(session, workspace_id)
        require_membership(session, workspace_id, user.id)
        agent = session.scalar(
            select(AgentRecord).where(
                AgentRecord.id == agent_id, AgentRecord.workspace_id == workspace_id
            ).with_for_update()
        )
        if agent is not None and agent.created_by != user.id:
            require_membership(session, workspace_id, user.id, roles=ADMIN_ROLES)
        if agent is None:
            raise NotFound("Agent not found")
        if agent.draft_runtime_type != "native":
            raise InvalidConfiguration("Only native configuration is supported in P1")
        if not agent.draft_model_profile_version_id:
            raise InvalidConfiguration("Agent must reference a model profile version")
        model_profile, model_version = verify_model_version(
            session, workspace_id, agent.draft_model_profile_version_id
        )
        authorize_model(session, workspace_id, user.id, model_version.id)
        if model_version.credential_reference_id:
            credential = session.get(CredentialReferenceRecord, model_version.credential_reference_id)
            if credential is None or credential.workspace_id != workspace_id or credential.status != "active":
                raise InvalidConfiguration("Credential reference is unavailable")
        draft_bindings = list(
            session.scalars(
                select(AgentDraftBindingRecord).where(AgentDraftBindingRecord.agent_id == agent.id)
            )
        )
        for binding in draft_bindings:
            authorize_resource(
                session, workspace_id, binding.kind, binding.resource_id,
                source_workspace_id=binding.source_workspace_id,
                resource_version_id=binding.resource_version_id, permission="use"
            )
        version_number = agent.version_counter + 1
        snapshot = {
            "agent_id": str(agent.id), "version": version_number, "name": agent.name,
            "description": agent.description, "runtime_type": agent.draft_runtime_type,
            "instructions": agent.draft_instructions, "model_profile_id": str(model_profile.id),
            "model_profile_version_id": str(model_version.id), "budgets": agent.draft_budgets,
            "bindings": [binding_snapshot(row) for row in draft_bindings],
        }
        version = AgentVersionRecord(
            id=new_id(), agent_id=agent.id, workspace_id=workspace_id,
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
                    source_workspace_id=binding.source_workspace_id,
                    binding_config=clean_public_options(binding.binding_config, "binding_config"),
                )
            )
        agent.version_counter = version_number
        agent.published_version_id = version.id
        agent.status = "published"
        agent.updated_at = now
        audit(session, workspace_id, user.id, "agent.published", "agent_version", str(version.id),
              {"agent_id": str(agent.id), "version": version_number, "content_hash": version.content_hash})
    return version


def get_agent(session: Session, workspace_id: UUID, agent_id: UUID):
    agent = session.scalar(
        select(AgentRecord).where(AgentRecord.id == agent_id, AgentRecord.workspace_id == workspace_id)
    )
    if agent is None:
        raise NotFound("Agent not found")
    draft_bindings = list(
        session.scalars(select(AgentDraftBindingRecord).where(AgentDraftBindingRecord.agent_id == agent.id))
    )
    return agent, draft_bindings


def list_agents(session: Session, workspace_id: UUID) -> list[AgentRecord]:
    return list(
        session.scalars(
            select(AgentRecord).where(AgentRecord.workspace_id == workspace_id).order_by(AgentRecord.created_at)
        )
    )


def verify_model_version(session: Session, workspace_id: UUID, version_id: UUID):
    row = session.execute(
        select(ModelProfileRecord, ModelProfileVersionRecord)
        .join(ModelProfileVersionRecord, ModelProfileVersionRecord.profile_id == ModelProfileRecord.id)
        .where(
            ModelProfileRecord.workspace_id == workspace_id,
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
        source_workspace_id = UUID(str(raw["source_workspace_id"]))
        version_id = str(raw.get("resource_version_id") or "")
        key = (kind, resource_id, version_id, str(source_workspace_id))
        if key in seen:
            raise Conflict("Duplicate agent resource binding")
        seen.add(key)
        session.add(
            AgentDraftBindingRecord(
                id=new_id(), agent_id=agent.id, kind=kind, resource_id=resource_id,
                resource_version_id=version_id, source_workspace_id=source_workspace_id,
                binding_config=clean_public_options(raw.get("config", {}), "binding_config"),
            )
        )


def binding_snapshot(binding: AgentDraftBindingRecord | ResourceBindingRecord) -> dict[str, Any]:
    return {
        "kind": binding.kind,
        "resource_id": binding.resource_id,
        "resource_version_id": binding.resource_version_id or None,
        "source_workspace_id": str(binding.source_workspace_id),
        "config": binding.binding_config,
    }
