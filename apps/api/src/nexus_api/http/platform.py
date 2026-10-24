from __future__ import annotations

import json
import time

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus_core.platform import Principal, WorkspaceRole
from nexus_platform.agents import service as agents
from nexus_platform.identity.service import require_membership, require_workspace, resolve_user
from nexus_platform.models import service as models
from nexus_platform.models.credentials import create_credential_reference
from nexus_platform.persistence.models import (
    AgentDraftBindingRecord,
    AgentVersionRecord,
    AuditRecord,
    MembershipRecord,
    ModelProfileRecord,
    ModelProfileVersionRecord,
    ResourceGrantRecord,
    ResourceBindingRecord,
)
from nexus_platform.runs import service as runs
from nexus_platform.sessions import service as sessions
from nexus_platform.workspaces import service as workspaces
from nexus_platform.workspaces.service import ADMIN_ROLES
from nexus_api.dependencies.platform import get_database_session, get_principal
from nexus_api.schemas.platform import (
    AgentDraftInput,
    AgentView,
    AgentVersionView,
    CredentialReferenceInput,
    CredentialReferenceView,
    MemberCreate,
    MemberRoleUpdate,
    MemberView,
    ModelProfileCreate,
    ModelProfileUpdate,
    ModelProfileVersionView,
    ModelProfileView,
    ResourceGrantCreate,
    ResourceGrantView,
    RunCreate,
    RunEventView,
    RunView,
    SessionCreate,
    SessionView,
    WorkspaceCreate,
    WorkspaceView,
)

router = APIRouter(prefix="/api/v1", tags=["platform"])


@router.post("/workspaces", response_model=WorkspaceView, status_code=status.HTTP_201_CREATED)
def create_workspace(
    body: WorkspaceCreate,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_database_session),
):
    row = workspaces.create_workspace(db, principal, body.name)
    return workspace_view(row, "owner")


@router.get("/workspaces", response_model=list[WorkspaceView])
def list_workspaces(
    principal: Principal = Depends(get_principal), db: Session = Depends(get_database_session)
):
    return [workspace_view(row, role) for row, role in workspaces.list_workspaces(db, principal)]


@router.post(
    "/workspaces/{workspace_id}/members", response_model=MemberView, status_code=status.HTTP_201_CREATED
)
def add_workspace_member(
    workspace_id: UUID,
    body: MemberCreate,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_database_session),
):
    row = workspaces.add_member(
        db, principal, workspace_id, Principal(id=body.subject, issuer=body.issuer), WorkspaceRole(body.role)
    )
    return MemberView.model_validate(row, from_attributes=True)


@router.get("/workspaces/{workspace_id}/members", response_model=list[MemberView])
def list_workspace_members(
    workspace_id: UUID,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_database_session),
):
    with db.begin():
        user = resolve_user(db, principal)
        require_workspace(db, workspace_id)
        require_membership(db, workspace_id, user.id, roles=ADMIN_ROLES)
        rows = list(
            db.scalars(
                select(MembershipRecord)
                .where(MembershipRecord.workspace_id == workspace_id, MembershipRecord.status == "active")
                .order_by(MembershipRecord.joined_at)
            )
        )
    return [MemberView.model_validate(row, from_attributes=True) for row in rows]


@router.patch("/workspaces/{workspace_id}/members/{member_id}", response_model=MemberView)
def update_workspace_member(
    workspace_id: UUID,
    member_id: UUID,
    body: MemberRoleUpdate,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_database_session),
):
    row = workspaces.update_member_role(db, principal, workspace_id, member_id, WorkspaceRole(body.role))
    return MemberView.model_validate(row, from_attributes=True)


@router.delete("/workspaces/{workspace_id}/members/{member_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_workspace_member(
    workspace_id: UUID,
    member_id: UUID,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_database_session),
):
    workspaces.remove_member(db, principal, workspace_id, member_id)


@router.post("/workspaces/{workspace_id}/resource-grants", response_model=ResourceGrantView)
def create_resource_grant(
    workspace_id: UUID,
    body: ResourceGrantCreate,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_database_session),
):
    row = workspaces.grant_resource(
        db, principal, source_workspace_id=body.source_workspace_id, target_workspace_id=workspace_id,
        kind=body.kind, resource_id=body.resource_id, permissions=body.permissions,
    )
    return ResourceGrantView.model_validate(row, from_attributes=True)


@router.delete("/resource-grants/{grant_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_resource_grant(
    grant_id: UUID,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_database_session),
):
    workspaces.revoke_resource_grant(db, principal, grant_id)


@router.post(
    "/workspaces/{workspace_id}/model-profiles", response_model=ModelProfileView,
    status_code=status.HTTP_201_CREATED,
)
def create_model_profile(
    workspace_id: UUID,
    body: ModelProfileCreate,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_database_session),
):
    profile, version = models.create_model_profile(
        db, principal, workspace_id, name=body.name, provider=body.provider, model_name=body.model_name,
        options=body.options, credential_reference_id=body.credential_reference_id,
    )
    return model_profile_view(profile, version)


@router.post(
    "/workspaces/{workspace_id}/credential-references",
    response_model=CredentialReferenceView,
    status_code=status.HTTP_201_CREATED,
)
def add_credential_reference(
    workspace_id: UUID,
    body: CredentialReferenceInput,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_database_session),
):
    row = create_credential_reference(
        db, principal, workspace_id, backend=body.backend, handle=body.handle
    )
    return CredentialReferenceView.model_validate(row, from_attributes=True)


@router.get("/workspaces/{workspace_id}/model-profiles", response_model=list[ModelProfileView])
def list_model_profiles(
    workspace_id: UUID,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_database_session),
):
    with db.begin():
        user = resolve_user(db, principal)
        require_workspace(db, workspace_id)
        require_membership(db, workspace_id, user.id, roles=ADMIN_ROLES)
        profiles = list(
            db.scalars(
                select(ModelProfileRecord).where(ModelProfileRecord.workspace_id == workspace_id)
                .order_by(ModelProfileRecord.created_at)
            )
        )
        items = []
        for profile in profiles:
            version = db.get(ModelProfileVersionRecord, profile.current_version_id) if profile.current_version_id else None
            items.append(model_profile_view(profile, version))
    return items


@router.put(
    "/workspaces/{workspace_id}/model-profiles/{profile_id}/versions",
    response_model=ModelProfileVersionView,
    status_code=status.HTTP_201_CREATED,
)
def create_model_profile_version(
    workspace_id: UUID,
    profile_id: UUID,
    body: ModelProfileUpdate,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_database_session),
):
    version = models.update_model_profile(
        db, principal, workspace_id, profile_id, model_name=body.model_name, options=body.options,
        credential_reference_id=body.credential_reference_id,
    )
    return model_version_view(version)


@router.post("/workspaces/{workspace_id}/agents", response_model=AgentView, status_code=status.HTTP_201_CREATED)
def create_agent(
    workspace_id: UUID,
    body: AgentDraftInput,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_database_session),
):
    row = agents.create_agent(
        db, principal, workspace_id, name=body.name, description=body.description,
        runtime_type=body.runtime_type, instructions=body.instructions,
        model_profile_version_id=body.model_profile_version_id, budgets=body.budgets,
        bindings=bindings_data(body.resource_bindings, workspace_id),
    )
    _, binding_rows = agents.get_agent(db, workspace_id, row.id)
    return agent_view(row, binding_rows)


@router.get("/workspaces/{workspace_id}/agents", response_model=list[AgentView])
def list_agents(
    workspace_id: UUID,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_database_session),
):
    with db.begin():
        user = resolve_user(db, principal)
        require_workspace(db, workspace_id)
        membership = require_membership(db, workspace_id, user.id)
        rows = agents.list_agents(db, workspace_id)
        output = []
        for row in rows:
            if membership.role in ADMIN_ROLES:
                bindings = list(db.scalars(
                    select(AgentDraftBindingRecord).where(AgentDraftBindingRecord.agent_id == row.id)
                ))
                output.append((row, bindings, None))
            elif row.published_version_id is not None:
                version = db.get(AgentVersionRecord, row.published_version_id)
                bindings = list(db.scalars(
                    select(ResourceBindingRecord).where(ResourceBindingRecord.agent_version_id == version.id)
                )) if version else []
                if version is not None:
                    output.append((row, bindings, version))
    return [agent_view(row, bindings, public_version) for row, bindings, public_version in output]


@router.get("/workspaces/{workspace_id}/agents/{agent_id}", response_model=AgentView)
def get_agent(
    workspace_id: UUID,
    agent_id: UUID,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_database_session),
):
    with db.begin():
        user = resolve_user(db, principal)
        require_workspace(db, workspace_id)
        membership = require_membership(db, workspace_id, user.id)
        row, bindings = agents.get_agent(db, workspace_id, agent_id)
        public_version = None
        if membership.role not in ADMIN_ROLES:
            public_version = db.get(AgentVersionRecord, row.published_version_id) if row.published_version_id else None
            if public_version is None:
                from nexus_platform.errors import NotFound
                raise NotFound("Agent not found")
            bindings = list(db.scalars(
                select(ResourceBindingRecord).where(ResourceBindingRecord.agent_version_id == public_version.id)
            ))
    return agent_view(row, bindings, public_version)


@router.put("/workspaces/{workspace_id}/agents/{agent_id}", response_model=AgentView)
def update_agent(
    workspace_id: UUID,
    agent_id: UUID,
    body: AgentDraftInput,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_database_session),
):
    row = agents.update_agent_draft(
        db, principal, workspace_id, agent_id, name=body.name, description=body.description,
        runtime_type=body.runtime_type, instructions=body.instructions,
        model_profile_version_id=body.model_profile_version_id, budgets=body.budgets,
        bindings=bindings_data(body.resource_bindings, workspace_id),
    )
    _, bindings = agents.get_agent(db, workspace_id, agent_id)
    return agent_view(row, bindings)


@router.post(
    "/workspaces/{workspace_id}/agents/{agent_id}/publish", response_model=AgentVersionView,
    status_code=status.HTTP_201_CREATED,
)
def publish_agent(
    workspace_id: UUID,
    agent_id: UUID,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_database_session),
):
    row = agents.publish_agent(db, principal, workspace_id, agent_id)
    return AgentVersionView.model_validate(row, from_attributes=True)


@router.post("/workspaces/{workspace_id}/sessions", response_model=SessionView, status_code=201)
def create_session(
    workspace_id: UUID,
    body: SessionCreate,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_database_session),
):
    row = sessions.create_session(
        db, principal, workspace_id, agent_version_id=body.agent_version_id, title=body.title
    )
    return SessionView.model_validate(row, from_attributes=True)


@router.get("/workspaces/{workspace_id}/sessions", response_model=list[SessionView])
def list_sessions(
    workspace_id: UUID,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_database_session),
):
    rows = sessions.list_sessions(db, principal, workspace_id)
    return [SessionView.model_validate(row, from_attributes=True) for row in rows]


@router.post("/workspaces/{workspace_id}/sessions/{session_id}/runs", response_model=RunView, status_code=202)
def create_run(
    workspace_id: UUID,
    session_id: UUID,
    body: RunCreate,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_database_session),
):
    key = (idempotency_key or str(request.state.request_id)).strip()
    row, replayed = runs.create_run(
        db, principal, workspace_id, session_id, message=body.message, idempotency_key=key
    )
    request.state.idempotent_replay = replayed
    return RunView.model_validate(row, from_attributes=True)


@router.get("/workspaces/{workspace_id}/runs/{run_id}", response_model=RunView)
def get_run(
    workspace_id: UUID,
    run_id: UUID,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_database_session),
):
    return RunView.model_validate(runs.get_run(db, principal, workspace_id, run_id), from_attributes=True)


@router.get("/workspaces/{workspace_id}/runs/{run_id}/events", response_model=list[RunEventView])
def list_run_events(
    workspace_id: UUID,
    run_id: UUID,
    request: Request,
    after_sequence: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1, le=500),
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_database_session),
):
    cursor = after_sequence
    if last_event_id is not None:
        if not last_event_id.isdecimal() or len(last_event_id) > 18:
            raise ValueError("Last-Event-ID must be a nonnegative sequence")
        cursor = max(cursor, int(last_event_id))
    runs.get_run(db, principal, workspace_id, run_id)
    if 'text/event-stream' in request.headers.get('accept', ''):
        def stream():
            nonlocal cursor
            while True:
                try:
                    rows = runs.list_events(db, principal, workspace_id, run_id, cursor, limit)
                    run = runs.get_run(db, principal, workspace_id, run_id)
                except Exception:
                    yield 'event: stream.closed\ndata: {}\n\n'
                    return
                for row in rows:
                    data = event_view(row).model_dump_json()
                    yield f'id: {row.sequence}\nevent: run.event\ndata: {data}\n\n'
                    cursor = row.sequence
                if len(rows) == limit:
                    continue
                if run.status in ('completed', 'failed', 'cancelled', 'interrupted', 'waiting_input', 'waiting_approval'):
                    return
                yield ': heartbeat\n\n'
                time.sleep(0.25)
        return StreamingResponse(stream(), media_type='text/event-stream',
            headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})
    return [event_view(row) for row in runs.list_events(db, principal, workspace_id, run_id, cursor, limit)]


def event_view(row):
    return RunEventView(event_id=row.id, run_id=row.run_id, sequence=row.sequence, event_type=row.event_type,
        schema_version=row.schema_version, payload=row.payload, occurred_at=row.occurred_at)


@router.post("/workspaces/{workspace_id}/runs/{run_id}/cancel", response_model=RunView, status_code=202)
def cancel_run(
    workspace_id: UUID,
    run_id: UUID,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_database_session),
):
    return RunView.model_validate(runs.request_cancel(db, principal, workspace_id, run_id), from_attributes=True)


@router.get("/workspaces/{workspace_id}/audit", response_model=list[dict[str, Any]])
def list_audit_records(
    workspace_id: UUID,
    limit: int = Query(default=100, ge=1, le=500),
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_database_session),
):
    with db.begin():
        user = resolve_user(db, principal)
        require_workspace(db, workspace_id)
        require_membership(db, workspace_id, user.id, roles=ADMIN_ROLES)
        rows = list(
            db.scalars(
                select(AuditRecord).where(AuditRecord.workspace_id == workspace_id)
                .order_by(AuditRecord.created_at.desc()).limit(limit)
            )
        )
    return [{
        "id": row.id, "actor_user_id": row.actor_user_id, "action": row.action,
        "target_type": row.target_type, "target_id": row.target_id, "result": row.result,
        "metadata": row.metadata_json, "created_at": row.created_at,
    } for row in rows]


def workspace_view(row, role: str) -> WorkspaceView:
    return WorkspaceView(id=row.id, name=row.name, role=role, status=row.status, created_at=row.created_at)


def model_profile_view(profile, version) -> ModelProfileView:
    return ModelProfileView(
        id=profile.id, workspace_id=profile.workspace_id, name=profile.name, provider=profile.provider,
        current_version=model_version_view(version) if version else None, created_at=profile.created_at,
    )


def model_version_view(row) -> ModelProfileVersionView:
    return ModelProfileVersionView.model_validate(row, from_attributes=True)


def agent_view(row, bindings, public_version=None) -> AgentView:
    version = public_version
    return AgentView(
        id=row.id, workspace_id=row.workspace_id, name=version.name if version else row.name,
        description=version.description if version else row.description,
        status="published" if version else row.status,
        published_version_id=row.published_version_id, version_counter=row.version_counter,
        current_version=AgentVersionView.model_validate(version, from_attributes=True) if version else None,
        runtime_type=version.runtime_type if version else row.draft_runtime_type,
        instructions=version.instructions if version else row.draft_instructions,
        model_profile_version_id=version.model_profile_version_id if version else row.draft_model_profile_version_id,
        budgets=version.budgets if version else row.draft_budgets,
        resource_bindings=[{
            "kind": binding.kind, "resource_id": binding.resource_id,
            "resource_version_id": binding.resource_version_id or None,
            "source_workspace_id": binding.source_workspace_id, "config": binding.binding_config,
        } for binding in bindings],
        created_at=row.created_at, updated_at=row.updated_at,
    )


def bindings_data(bindings, default_workspace_id: UUID) -> list[dict[str, Any]]:
    return [
        {
            "kind": binding.kind,
            "resource_id": binding.resource_id,
            "resource_version_id": binding.resource_version_id,
            "source_workspace_id": binding.source_workspace_id or default_workspace_id,
            "config": binding.config,
        }
        for binding in bindings
    ]


@router.get('/workspaces/{workspace_id}/sessions/{session_id}/messages')
def conversation_history(workspace_id: UUID, session_id: UUID,
    after_sequence: int = Query(default=0, ge=0), limit: int = Query(default=200, ge=1, le=500),
    principal: Principal = Depends(get_principal), db: Session = Depends(get_database_session)):
    messages, latest = sessions.conversation(db, principal, workspace_id, session_id,
                                            after_sequence=after_sequence, limit=limit)
    return {'messages': [{'id': row.id, 'run_id': row.run_id, 'sequence': row.sequence,
                          'role': row.role, 'content': row.content, 'created_at': row.created_at} for row in messages],
            'latest_run': RunView.model_validate(latest, from_attributes=True) if latest else None}


@router.get('/workspaces/{workspace_id}/runs/{run_id}/input')
def pending_input(workspace_id: UUID, run_id: UUID, principal: Principal = Depends(get_principal),
                  db: Session = Depends(get_database_session)):
    from nexus_platform.persistence.models import InputRequestRecord
    runs.get_run(db, principal, workspace_id, run_id)
    with db.begin():
        pending = db.scalar(select(InputRequestRecord).where(InputRequestRecord.run_id == run_id,
                            InputRequestRecord.responded_at.is_(None)).order_by(InputRequestRecord.created_at.desc()))
        return {'input_request_id': pending.id, 'question': pending.question} if pending else None


from nexus_api.schemas.platform import InputResponse


@router.post('/workspaces/{workspace_id}/runs/{run_id}/input', response_model=RunView, status_code=202)
def submit_input(workspace_id: UUID, run_id: UUID, body: InputResponse,
    idempotency_key: str = Header(alias='Idempotency-Key'),
    principal: Principal = Depends(get_principal), db: Session = Depends(get_database_session)):
    from nexus_platform.runs.execution import respond_input
    row = respond_input(db, principal, workspace_id, run_id, body.input_request_id, body.response, idempotency_key)
    return RunView.model_validate(row, from_attributes=True)


@router.get('/workspaces/{workspace_id}/runs/{run_id}/memory-drafts')
def memory_drafts(workspace_id: UUID, run_id: UUID, principal: Principal = Depends(get_principal),
                  db: Session = Depends(get_database_session)):
    from nexus_platform.persistence.models import MemoryDraftRecord
    runs.get_run(db, principal, workspace_id, run_id)
    with db.begin():
        rows = db.scalars(select(MemoryDraftRecord).where(MemoryDraftRecord.source_run_id == run_id,
                                                         MemoryDraftRecord.workspace_id == workspace_id))
        return [{'id': row.id, 'kind': row.kind, 'scope': row.scope, 'diff': row.diff,
                 'status': row.status, 'source_run_id': row.source_run_id} for row in rows]


@router.post('/workspaces/{workspace_id}/tools/{name}/enable', status_code=201)
def enable_builtin(workspace_id: UUID, name: str, principal: Principal = Depends(get_principal),
                   db: Session = Depends(get_database_session)):
    from nexus_tools.builtins import builtins
    from nexus_platform.errors import NotFound
    tool = builtins(None).get(name, 'v1')
    if not tool:
        raise NotFound('Tool not found')
    with db.begin():
        user = resolve_user(db, principal)
        require_workspace(db, workspace_id)
        require_membership(db, workspace_id, user.id, roles=ADMIN_ROLES)
        workspaces.register_resource(db, workspace_id=workspace_id, kind='tool', resource_id=name, version_id='v1')
        workspaces.audit(db, workspace_id, user.id, 'tool.enabled', 'tool', name)
    return {'kind': 'tool', 'resource_id': name, 'resource_version_id': 'v1', 'source_workspace_id': workspace_id}
