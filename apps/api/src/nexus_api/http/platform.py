from __future__ import annotations

import json
import time

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, status
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus_core.platform import Principal, TenantRole
from nexus_platform.agents import service as agents
from nexus_platform.memory import snapshots
from nexus_platform.agents.access import require_agent_permission, set_agent_grants, visible_agent_ids
from nexus_platform.errors import NotFound
from nexus_platform.identity.service import require_membership, require_tenant, resolve_user
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
from nexus_platform.tenants import service as tenants
from nexus_platform.authz import resources as authz
from nexus_platform.authz.audit import audit
from nexus_platform.tenants.service import ADMIN_ROLES
from nexus_platform.authz.permissions import require_api_permission
from nexus_api.dependencies.platform import get_database_session, get_principal, get_tenant_header
from nexus_api.schemas.platform import (
    InputResponse,
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
    AdminAgentView,
    MemorySnapshotView,
    SessionView,
    TenantCreate,
    TenantUpdate,
    TenantView,
)

router = APIRouter(prefix="/api/v1", tags=["platform"])


@router.post("/tenants", response_model=TenantView, status_code=status.HTTP_201_CREATED)
def create_tenant(
    body: TenantCreate,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_database_session),
):
    row = tenants.create_tenant(db, principal, body.name)
    return tenant_view(row, "owner")


@router.get("/tenants/current", response_model=TenantView)
def get_current_tenant(
    tenant_id: UUID | None = Depends(get_tenant_header),
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_database_session),
):
    """The space named by `X-Tenant-ID`. Membership is required; a missing header is a 404."""
    if tenant_id is None:
        raise NotFound("No current space was selected")
    row, role = tenants.current_space(db, principal, tenant_id)
    return tenant_view(row, role)


@router.patch("/tenants/current", response_model=TenantView)
def update_current_tenant(
    body: TenantUpdate,
    tenant_id: UUID | None = Depends(get_tenant_header),
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_database_session),
):
    if tenant_id is None:
        raise NotFound("No current space was selected")
    row = tenants.update_space(db, principal, tenant_id, name=body.name)
    _, role = tenants.current_space(db, principal, tenant_id)
    return tenant_view(row, role)


@router.get("/tenants", response_model=list[TenantView])
def list_tenants(
    principal: Principal = Depends(get_principal), db: Session = Depends(get_database_session)
):
    return [tenant_view(row, role) for row, role in tenants.list_tenants(db, principal)]


@router.post(
    "/tenants/{tenant_id}/members", response_model=MemberView, status_code=status.HTTP_201_CREATED
)
def add_tenant_member(
    tenant_id: UUID,
    body: MemberCreate,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_database_session),
):
    row = tenants.add_member(
        db, principal, tenant_id, Principal(id=body.subject, issuer=body.issuer), TenantRole(body.role)
    )
    return MemberView.model_validate(row, from_attributes=True)


@router.get("/tenants/{tenant_id}/members", response_model=list[MemberView])
def list_tenant_members(
    tenant_id: UUID,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_database_session),
):
    with db.begin():
        user = resolve_user(db, principal)
        require_tenant(db, tenant_id)
        require_membership(db, tenant_id, user.id)
        require_api_permission(db, tenant_id, user.id, "members:manage")
        rows = list(
            db.scalars(
                select(MembershipRecord)
                .where(MembershipRecord.tenant_id == tenant_id, MembershipRecord.status == "active")
                .order_by(MembershipRecord.joined_at)
            )
        )
    return [MemberView.model_validate(row, from_attributes=True) for row in rows]


@router.patch("/tenants/{tenant_id}/members/{member_id}", response_model=MemberView)
def update_tenant_member(
    tenant_id: UUID,
    member_id: UUID,
    body: MemberRoleUpdate,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_database_session),
):
    row = tenants.update_member_role(db, principal, tenant_id, member_id, TenantRole(body.role))
    return MemberView.model_validate(row, from_attributes=True)


@router.delete("/tenants/{tenant_id}/members/{member_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_tenant_member(
    tenant_id: UUID,
    member_id: UUID,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_database_session),
):
    tenants.remove_member(db, principal, tenant_id, member_id)


@router.post("/tenants/{tenant_id}/resource-grants", response_model=ResourceGrantView)
def create_resource_grant(
    tenant_id: UUID,
    body: ResourceGrantCreate,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_database_session),
):
    row = authz.grant_resource(
        db, principal, source_tenant_id=body.source_tenant_id, target_tenant_id=tenant_id,
        kind=body.kind, resource_id=body.resource_id, permissions=body.permissions,
    )
    return ResourceGrantView.model_validate(row, from_attributes=True)


@router.delete("/resource-grants/{grant_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_resource_grant(
    grant_id: UUID,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_database_session),
):
    authz.revoke_resource_grant(db, principal, grant_id)


@router.post(
    "/tenants/{tenant_id}/model-profiles", response_model=ModelProfileView,
    status_code=status.HTTP_201_CREATED,
)
def create_model_profile(
    tenant_id: UUID,
    body: ModelProfileCreate,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_database_session),
):
    profile, version = models.create_model_profile(
        db, principal, tenant_id, name=body.name, provider=body.provider, model_name=body.model_name,
        options=body.options, credential_reference_id=body.credential_reference_id,
    )
    return model_profile_view(profile, version)


@router.post(
    "/tenants/{tenant_id}/credential-references",
    response_model=CredentialReferenceView,
    status_code=status.HTTP_201_CREATED,
)
def add_credential_reference(
    tenant_id: UUID,
    body: CredentialReferenceInput,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_database_session),
):
    row = create_credential_reference(
        db, principal, tenant_id, backend=body.backend, handle=body.handle
    )
    return CredentialReferenceView.model_validate(row, from_attributes=True)


@router.get("/tenants/{tenant_id}/model-profiles", response_model=list[ModelProfileView])
def list_model_profiles(
    tenant_id: UUID,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_database_session),
):
    with db.begin():
        user = resolve_user(db, principal)
        require_tenant(db, tenant_id)
        require_membership(db, tenant_id, user.id)
        require_api_permission(db, tenant_id, user.id, "models:manage")
        profiles = list(
            db.scalars(
                select(ModelProfileRecord).where(ModelProfileRecord.tenant_id == tenant_id)
                .order_by(ModelProfileRecord.created_at)
            )
        )
        items = []
        for profile in profiles:
            version = db.get(ModelProfileVersionRecord, profile.current_version_id) if profile.current_version_id else None
            from nexus_platform.models.provider_settings import authorize_model
            from nexus_platform.errors import NotFound
            try:
                if version:
                    authorize_model(db, tenant_id, user.id, version.id)
            except NotFound:
                continue
            items.append(model_profile_view(profile, version))
    return items


@router.put(
    "/tenants/{tenant_id}/model-profiles/{profile_id}/versions",
    response_model=ModelProfileVersionView,
    status_code=status.HTTP_201_CREATED,
)
def create_model_profile_version(
    tenant_id: UUID,
    profile_id: UUID,
    body: ModelProfileUpdate,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_database_session),
):
    version = models.update_model_profile(
        db, principal, tenant_id, profile_id, model_name=body.model_name, options=body.options,
        credential_reference_id=body.credential_reference_id,
    )
    return model_version_view(version)


@router.post("/tenants/{tenant_id}/agents", response_model=AgentView, status_code=status.HTTP_201_CREATED)
def create_agent(
    tenant_id: UUID,
    body: AgentDraftInput,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_database_session),
):
    row = agents.create_agent(
        db, principal, tenant_id, name=body.name, description=body.description,
        runtime_type=body.runtime_type, instructions=body.instructions,
        model_profile_version_id=body.model_profile_version_id, budgets=body.budgets,
        bindings=bindings_data(body.resource_bindings, tenant_id),
    )
    _, binding_rows = agents.get_agent(db, tenant_id, row.id)
    return agent_view(row, binding_rows)


@router.get("/tenants/{tenant_id}/agents", response_model=list[AgentView])
def list_agents(
    tenant_id: UUID,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_database_session),
):
    with db.begin():
        user = resolve_user(db, principal)
        require_tenant(db, tenant_id)
        membership = require_membership(db, tenant_id, user.id)
        visible = visible_agent_ids(db, tenant_id, user.id)
        rows = [row for row in agents.list_agents(db, tenant_id) if visible is None or row.id in visible]
        output = []
        for row in rows:
            from nexus_platform.models.provider_settings import authorize_model
            from nexus_platform.errors import NotFound
            version = db.get(AgentVersionRecord, row.published_version_id) if row.published_version_id else None
            model_id = row.draft_model_profile_version_id if membership.role in ADMIN_ROLES else (version.model_profile_version_id if version else None)
            if model_id:
                try:
                    authorize_model(db, tenant_id, user.id, model_id)
                except NotFound:
                    continue
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


@router.get("/tenants/{tenant_id}/agents/{agent_id}", response_model=AgentView)
def get_agent(
    tenant_id: UUID,
    agent_id: UUID,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_database_session),
):
    with db.begin():
        user = resolve_user(db, principal)
        require_tenant(db, tenant_id)
        membership = require_membership(db, tenant_id, user.id)
        row, bindings = agents.get_agent(db, tenant_id, agent_id)
        require_agent_permission(db, tenant_id, user.id, row, "view")
        public_version = None
        from nexus_platform.models.provider_settings import authorize_model
        if membership.role in ADMIN_ROLES and row.draft_model_profile_version_id:
            authorize_model(db, tenant_id, user.id, row.draft_model_profile_version_id)
        if membership.role not in ADMIN_ROLES:
            public_version = db.get(AgentVersionRecord, row.published_version_id) if row.published_version_id else None
            if public_version is None:
                from nexus_platform.errors import NotFound
                raise NotFound("Agent not found")
            authorize_model(db, tenant_id, user.id, public_version.model_profile_version_id)
            bindings = list(db.scalars(
                select(ResourceBindingRecord).where(ResourceBindingRecord.agent_version_id == public_version.id)
            ))
    return agent_view(row, bindings, public_version)


@router.put("/tenants/{tenant_id}/agents/{agent_id}", response_model=AgentView)
def update_agent(
    tenant_id: UUID,
    agent_id: UUID,
    body: AgentDraftInput,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_database_session),
):
    row = agents.update_agent_draft(
        db, principal, tenant_id, agent_id, name=body.name, description=body.description,
        runtime_type=body.runtime_type, instructions=body.instructions,
        model_profile_version_id=body.model_profile_version_id, budgets=body.budgets,
        bindings=bindings_data(body.resource_bindings, tenant_id),
    )
    _, bindings = agents.get_agent(db, tenant_id, agent_id)
    return agent_view(row, bindings)


@router.post(
    "/tenants/{tenant_id}/agents/{agent_id}/publish", response_model=AgentVersionView,
    status_code=status.HTTP_201_CREATED,
)
def publish_agent(
    tenant_id: UUID,
    agent_id: UUID,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_database_session),
):
    row = agents.publish_agent(db, principal, tenant_id, agent_id)
    return AgentVersionView.model_validate(row, from_attributes=True)


@router.post("/tenants/{tenant_id}/sessions", response_model=SessionView, status_code=201)
def create_session(
    tenant_id: UUID,
    body: SessionCreate,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_database_session),
):
    row = sessions.create_session(
        db, principal, tenant_id, agent_version_id=body.agent_version_id, title=body.title
    )
    return SessionView.model_validate(row, from_attributes=True)


@router.get("/tenants/{tenant_id}/sessions", response_model=list[SessionView])
def list_sessions(
    tenant_id: UUID,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_database_session),
):
    rows = sessions.list_sessions(db, principal, tenant_id)
    return [SessionView.model_validate(row, from_attributes=True) for row in rows]


@router.get("/admin/tenants", response_model=list[TenantView])
def list_all_tenants(principal: Principal = Depends(get_principal), db: Session = Depends(get_database_session)):
    """Platform administrators only: every active space, for choosing a filter."""
    return [tenant_view(row, "") for row in tenants.list_all_tenants(db, principal)]


@router.get("/admin/summary")
def platform_summary(principal: Principal = Depends(get_principal), db: Session = Depends(get_database_session)):
    """Platform administrators only: read-only counts of enterprises, personal spaces and shared spaces."""
    return tenants.platform_summary(db, principal)


@router.get("/admin/agents", response_model=list[AdminAgentView])
def list_all_agents(principal: Principal = Depends(get_principal), db: Session = Depends(get_database_session)):
    """Platform administrators only: every agent across spaces, for the session filter."""
    rows = agents.list_all_agents_for_platform_admin(db, principal)
    return [AdminAgentView(id=row.id, tenant_id=row.tenant_id, name=row.name,
                           published_version_id=row.published_version_id) for row in rows]


@router.get("/admin/sessions", response_model=list[SessionView])
def list_all_sessions(
    tenant_id: UUID | None = None,
    agent_id: UUID | None = None,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_database_session),
):
    """Platform administrators only: sessions across spaces, filtered by space or agent."""
    rows = sessions.list_sessions_for_platform_admin(
        db, principal, tenant_id=tenant_id, agent_id=agent_id)
    return [SessionView.model_validate(row, from_attributes=True) for row in rows]


@router.get("/tenants/{tenant_id}/sessions/{session_id}/memory-snapshot", response_model=MemorySnapshotView)
def get_memory_snapshot(tenant_id: UUID, session_id: UUID, principal: Principal = Depends(get_principal),
                        db: Session = Depends(get_database_session)):
    """The session's memory index snapshot status. Only the session's owner may read it."""
    return MemorySnapshotView(**snapshots.snapshot_status(db, principal, tenant_id, session_id))


@router.post("/tenants/{tenant_id}/sessions/{session_id}/memory-snapshot/refresh", status_code=204)
def refresh_memory_snapshot(tenant_id: UUID, session_id: UUID, principal: Principal = Depends(get_principal),
                            db: Session = Depends(get_database_session)):
    """Rebuild the session's memory index from current memory on the next Run."""
    snapshots.refresh_snapshot(db, principal, tenant_id, session_id)
    return Response(status_code=204)


@router.post("/tenants/{tenant_id}/sessions/{session_id}/runs", response_model=RunView, status_code=202)
def create_run(
    tenant_id: UUID,
    session_id: UUID,
    body: RunCreate,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_database_session),
):
    key = (idempotency_key or str(request.state.request_id)).strip()
    row, replayed = runs.create_run(
        db, principal, tenant_id, session_id, message=body.message, idempotency_key=key
    )
    request.state.idempotent_replay = replayed
    view = RunView.model_validate(row, from_attributes=True)
    view.queue_position = runs.queue_position(db, row.id)
    return view


@router.get("/tenants/{tenant_id}/runs/{run_id}", response_model=RunView)
def get_run(
    tenant_id: UUID,
    run_id: UUID,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_database_session),
):
    return RunView.model_validate(runs.get_run(db, principal, tenant_id, run_id), from_attributes=True)


@router.get("/tenants/{tenant_id}/runs/{run_id}/events", response_model=list[RunEventView])
def list_run_events(
    tenant_id: UUID,
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
    runs.get_run(db, principal, tenant_id, run_id)
    if 'text/event-stream' in request.headers.get('accept', ''):
        def stream():
            nonlocal cursor
            while True:
                try:
                    run = runs.get_run(db, principal, tenant_id, run_id)
                    rows = runs.list_events(db, principal, tenant_id, run_id, cursor, limit)
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
    return [event_view(row) for row in runs.list_events(db, principal, tenant_id, run_id, cursor, limit)]


def event_view(row):
    return RunEventView(event_id=row.id, run_id=row.run_id, sequence=row.sequence, event_type=row.event_type,
        schema_version=row.schema_version, payload=row.payload, occurred_at=row.occurred_at)


@router.post("/tenants/{tenant_id}/runs/{run_id}/cancel", response_model=RunView, status_code=202)
def cancel_run(
    tenant_id: UUID,
    run_id: UUID,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_database_session),
):
    return RunView.model_validate(runs.request_cancel(db, principal, tenant_id, run_id), from_attributes=True)


@router.get("/tenants/{tenant_id}/audit", response_model=list[dict[str, Any]])
def list_audit_records(
    tenant_id: UUID,
    limit: int = Query(default=100, ge=1, le=500),
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_database_session),
):
    with db.begin():
        user = resolve_user(db, principal)
        require_tenant(db, tenant_id)
        require_membership(db, tenant_id, user.id)
        require_api_permission(db, tenant_id, user.id, "audit:read")
        rows = list(
            db.scalars(
                select(AuditRecord).where(AuditRecord.tenant_id == tenant_id)
                .order_by(AuditRecord.created_at.desc()).limit(limit)
            )
        )
    return [{
        "id": row.id, "actor_user_id": row.actor_user_id, "action": row.action,
        "target_type": row.target_type, "target_id": row.target_id, "result": row.result,
        "metadata": row.metadata_json, "created_at": row.created_at,
    } for row in rows]


def tenant_view(row, role: str) -> TenantView:
    return TenantView(id=row.id, name=row.name, kind=row.kind, role=role, status=row.status, created_at=row.created_at)


def model_profile_view(profile, version) -> ModelProfileView:
    return ModelProfileView(
        id=profile.id, tenant_id=profile.tenant_id, name=profile.name, provider=profile.provider,
        current_version=model_version_view(version) if version else None, created_at=profile.created_at,
    )


def model_version_view(row) -> ModelProfileVersionView:
    return ModelProfileVersionView.model_validate(row, from_attributes=True)


def agent_view(row, bindings, public_version=None) -> AgentView:
    version = public_version
    return AgentView(
        id=row.id, tenant_id=row.tenant_id, name=version.name if version else row.name,
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
            "source_tenant_id": binding.source_tenant_id, "config": binding.binding_config,
        } for binding in bindings],
        created_at=row.created_at, updated_at=row.updated_at,
    )


def bindings_data(bindings, default_tenant_id: UUID) -> list[dict[str, Any]]:
    return [
        {
            "kind": binding.kind,
            "resource_id": binding.resource_id,
            "resource_version_id": binding.resource_version_id,
            "source_tenant_id": binding.source_tenant_id or default_tenant_id,
            "config": binding.config,
        }
        for binding in bindings
    ]


@router.get('/tenants/{tenant_id}/sessions/{session_id}/messages')
def conversation_history(tenant_id: UUID, session_id: UUID,
    after_sequence: int = Query(default=0, ge=0), limit: int = Query(default=200, ge=1, le=500),
    principal: Principal = Depends(get_principal), db: Session = Depends(get_database_session)):
    messages, latest = sessions.conversation(db, principal, tenant_id, session_id,
                                            after_sequence=after_sequence, limit=limit)
    return {'messages': [{'id': row.id, 'run_id': row.run_id, 'sequence': row.sequence,
                          'role': 'system' if row.role == 'user' and row.runtime_metadata.get('origin') == 'runtime' else row.role,
                          'content': row.content, 'created_at': row.created_at} for row in messages],
            'latest_run': RunView.model_validate(latest, from_attributes=True) if latest else None}


@router.get('/tenants/{tenant_id}/runs/{run_id}/input')
def pending_input(tenant_id: UUID, run_id: UUID, principal: Principal = Depends(get_principal),
                  db: Session = Depends(get_database_session)):
    from nexus_platform.persistence.models import InputRequestRecord
    runs.get_run(db, principal, tenant_id, run_id)
    with db.begin():
        pending = db.scalar(select(InputRequestRecord).where(InputRequestRecord.run_id == run_id,
                            InputRequestRecord.responded_at.is_(None)).order_by(InputRequestRecord.created_at.desc()))
        return {'input_request_id': pending.id, 'question': pending.question, 'candidates': pending.candidates} if pending else None


@router.post('/tenants/{tenant_id}/runs/{run_id}/input', response_model=RunView, status_code=202)
def submit_input(tenant_id: UUID, run_id: UUID, body: InputResponse,
    idempotency_key: str = Header(alias='Idempotency-Key'),
    principal: Principal = Depends(get_principal), db: Session = Depends(get_database_session)):
    from nexus_platform.runs.execution import respond_input
    row = respond_input(db, principal, tenant_id, run_id, body.input_request_id, body.response, idempotency_key)
    return RunView.model_validate(row, from_attributes=True)


@router.get('/tenants/{tenant_id}/runs/{run_id}/memory-drafts')
def memory_drafts(tenant_id: UUID, run_id: UUID, principal: Principal = Depends(get_principal),
                  db: Session = Depends(get_database_session)):
    from nexus_platform.persistence.models import MemoryDraftRecord
    runs.get_run(db, principal, tenant_id, run_id)
    with db.begin():
        rows = db.scalars(select(MemoryDraftRecord).where(MemoryDraftRecord.source_run_id == run_id,
                                                         MemoryDraftRecord.tenant_id == tenant_id))
        return [{'id': row.id, 'kind': row.kind, 'scope': row.scope, 'diff': row.diff,
                 'status': row.status, 'source_run_id': row.source_run_id} for row in rows]


@router.post('/tenants/{tenant_id}/tools/{name}/enable', status_code=201)
def enable_builtin(tenant_id: UUID, name: str, principal: Principal = Depends(get_principal),
                   db: Session = Depends(get_database_session)):
    from nexus_tools.builtins import builtins
    from nexus_platform.errors import NotFound
    tool = builtins().get(name, 'v1')
    if not tool:
        raise NotFound('Tool not found')
    with db.begin():
        user = resolve_user(db, principal)
        require_tenant(db, tenant_id)
        require_membership(db, tenant_id, user.id)
        require_api_permission(db, tenant_id, user.id, "tools:manage")
        authz.register_resource(db, tenant_id=tenant_id, kind='tool', resource_id=name, version_id='v1')
        audit(db, tenant_id, user.id, 'tool.enabled', 'tool', name)
    return {'kind': 'tool', 'resource_id': name, 'resource_version_id': 'v1', 'source_tenant_id': tenant_id}
