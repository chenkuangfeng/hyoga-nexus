from __future__ import annotations

import json

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4, uuid5

from fastapi import APIRouter, Depends, Header, Query, Request, status
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus_core.platform import Principal, TenantRole
from nexus_core.run_events import BusEvent
from nexus_platform.agents import service as agents
from nexus_platform.auth import accounts
from nexus_platform.memory import snapshots
from nexus_platform.agents.access import can_maintain_agent, require_agent_permission, set_agent_grants, visible_agent_ids
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
    UserIdentityRecord,
    UserRecord,
)
from nexus_platform.runs import service as runs
from nexus_platform.runs import unknown as unknown_runs
from nexus_platform.runs.bus.stream import stream_run_events
from nexus_tools.builtins.registration import side_effects_by_name
from nexus_platform.runs.watchdog_service import acknowledge_watchdog, attention_required
from nexus_platform.sessions import service as sessions
from nexus_platform.tenants import service as tenants
from nexus_platform.authz import resources as authz
from nexus_platform.authz.audit import audit
from nexus_platform.tenants.service import ADMIN_ROLES
from nexus_platform.authz.permissions import require_api_permission
from nexus_api.dependencies.platform import get_database_session, get_principal, get_run_channels, get_tenant_header
from nexus_api.http.admin_routes import tenant_admin_route
from nexus_api.schemas.platform import (
    InputResponse,
    AgentDraftInput,
    AgentView,
    AgentVersionView,
    CredentialReferenceInput,
    CredentialReferenceView,
    MemberCreate,
    MemberRoleUpdate,
    MemberStatusUpdate,
    MemberView,
    ModelProfileCreate,
    ModelProfileUpdate,
    ModelProfileVersionView,
    ModelProfileView,
    ResourceGrantCreate,
    ResourceGrantView,
    RunCreate,
    RunEventView,
    RunTrajectoryRecordView,
    RunView,
    SessionCreate,
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
    fields = body.model_dump(exclude_unset=True)
    row = tenants.update_space(db, principal, tenant_id, name=fields.get("name"),
                               description=fields.get("description"))
    _, role = tenants.current_space(db, principal, tenant_id)
    return tenant_view(row, role)


@router.get("/tenants/{tenant_id}/admin", response_model=TenantView)
def get_tenant_admin_info(
    tenant_id: UUID,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_database_session),
):
    """Read enterprise details through the canonical management resource path."""
    row, role = tenants.current_space(db, principal, tenant_id)
    return tenant_view(row, role)


@router.patch("/tenants/{tenant_id}/admin", response_model=TenantView)
def update_tenant_admin_info(
    tenant_id: UUID,
    body: TenantUpdate,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_database_session),
):
    """Update enterprise details; the tenant service enforces owner/admin permissions."""
    fields = body.model_dump(exclude_unset=True)
    row = tenants.update_space(db, principal, tenant_id, name=fields.get("name"),
                               description=fields.get("description"))
    _, role = tenants.current_space(db, principal, tenant_id)
    return tenant_view(row, role)


@tenant_admin_route(router, "/tenants/{tenant_id}", methods=["DELETE"], status_code=status.HTTP_204_NO_CONTENT)
def delete_tenant(
    tenant_id: UUID,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_database_session),
):
    """Archive an enterprise space (owner only). Personal spaces cannot be deleted."""
    tenants.delete_space(db, principal, tenant_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/tenants", response_model=list[TenantView])
def list_tenants(
    principal: Principal = Depends(get_principal), db: Session = Depends(get_database_session)
):
    return [tenant_view(row, role) for row, role in tenants.list_tenants(db, principal)]


@tenant_admin_route(router, "/tenants/{tenant_id}/members", methods=["POST"], response_model=MemberView,
                    status_code=status.HTTP_201_CREATED)
def add_tenant_member(
    tenant_id: UUID,
    body: MemberCreate,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_database_session),
):
    row = tenants.add_member(
        db, principal, tenant_id, Principal(id=body.subject, issuer=body.issuer), TenantRole(body.role)
    )
    with db.begin():
        return _member_view(db, row)


@tenant_admin_route(router, "/tenants/{tenant_id}/members", methods=["GET"], response_model=list[MemberView])
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
                .where(MembershipRecord.tenant_id == tenant_id, MembershipRecord.status.in_(("active", "suspended")))
                .order_by(MembershipRecord.joined_at)
            )
        )
    with db.begin():
        return [_member_view(db, row) for row in rows]


def _member_view(db: Session, row) -> MemberView:
    """A membership row joined with its user's email, password-account username and display name."""
    user = db.get(UserRecord, row.user_id)
    username = db.scalar(select(UserIdentityRecord.external_id).where(
        UserIdentityRecord.user_id == row.user_id, UserIdentityRecord.provider == accounts.PASSWORD_PROVIDER))
    return MemberView(
        tenant_id=row.tenant_id, user_id=row.user_id, role=row.role, status=row.status, joined_at=row.joined_at,
        suspended_at=row.suspended_at,
        email=user.email if user else None, username=username,
        display_name=user.display_name if user else None,
    )


@tenant_admin_route(router, "/tenants/{tenant_id}/members/{member_id}", methods=["PATCH"], response_model=MemberView)
def update_tenant_member(
    tenant_id: UUID,
    member_id: UUID,
    body: MemberRoleUpdate,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_database_session),
):
    row = tenants.update_member_role(db, principal, tenant_id, member_id, TenantRole(body.role))
    with db.begin():
        return _member_view(db, row)


@tenant_admin_route(router, "/tenants/{tenant_id}/members/{member_id}/status", methods=["PATCH"], response_model=MemberView)
def update_tenant_member_status(
    tenant_id: UUID,
    member_id: UUID,
    body: MemberStatusUpdate,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_database_session),
):
    row = tenants.set_member_status(db, principal, tenant_id, member_id, body.status)
    with db.begin():
        return _member_view(db, row)


@tenant_admin_route(router, "/tenants/{tenant_id}/members/{member_id}", methods=["DELETE"], status_code=status.HTTP_204_NO_CONTENT)
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
    return agent_view(row, binding_rows, user_id=row.created_by, can_maintain=True)


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
            maintains = can_maintain_agent(db, tenant_id, user.id, row)
            # Drafts are shown to maintainers and, for governance, to owners and admins; others see the published
            # version only.
            sees_draft = maintains or membership.role in ADMIN_ROLES
            model_id = row.draft_model_profile_version_id if sees_draft else (version.model_profile_version_id if version else None)
            if model_id:
                try:
                    authorize_model(db, tenant_id, user.id, model_id)
                except NotFound:
                    continue
            if sees_draft:
                bindings = list(db.scalars(
                    select(AgentDraftBindingRecord).where(AgentDraftBindingRecord.agent_id == row.id)
                ))
                output.append((row, bindings, None, maintains))
            elif row.published_version_id is not None:
                version = db.get(AgentVersionRecord, row.published_version_id)
                bindings = list(db.scalars(
                    select(ResourceBindingRecord).where(ResourceBindingRecord.agent_version_id == version.id)
                )) if version else []
                if version is not None:
                    output.append((row, bindings, version, maintains))
    return [agent_view(row, bindings, public_version, user_id=user.id, can_maintain=maintains)
            for row, bindings, public_version, maintains in output]


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
        maintains = can_maintain_agent(db, tenant_id, user.id, row)
        sees_draft = maintains or membership.role in ADMIN_ROLES
        from nexus_platform.models.provider_settings import authorize_model
        if sees_draft and row.draft_model_profile_version_id:
            authorize_model(db, tenant_id, user.id, row.draft_model_profile_version_id)
        if not sees_draft:
            public_version = db.get(AgentVersionRecord, row.published_version_id) if row.published_version_id else None
            if public_version is None:
                from nexus_platform.errors import NotFound
                raise NotFound("Agent not found")
            authorize_model(db, tenant_id, user.id, public_version.model_profile_version_id)
            bindings = list(db.scalars(
                select(ResourceBindingRecord).where(ResourceBindingRecord.agent_version_id == public_version.id)
            ))
    return agent_view(row, bindings, public_version, user_id=user.id, can_maintain=maintains)


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
    return agent_view(row, bindings, can_maintain=True)


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
    run = runs.get_run(db, principal, tenant_id, run_id)
    view = RunView.model_validate(run, from_attributes=True)
    view.attention_required = attention_required(db, run.id)
    return view


@tenant_admin_route(router, "/tenants/{tenant_id}/admissions/unknown", methods=["GET"])
def list_unknown_admissions(
    tenant_id: UUID,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_database_session),
):
    """Sessions blocked because a worker was lost while running them: all for a tenant owner or admin, one's own otherwise."""
    return unknown_runs.list_unknown(db, principal, tenant_id, side_effects_by_name())


@tenant_admin_route(router, "/tenants/{tenant_id}/runs/{run_id}/resolve-unknown", methods=["POST"])
def resolve_unknown_run(
    tenant_id: UUID,
    run_id: UUID,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_database_session),
):
    """Clear the block an interrupted Run left on its session. The Run is not replayed. Idempotent."""
    return unknown_runs.resolve_unknown_run(db, principal, tenant_id, run_id)


@router.get("/tenants/{tenant_id}/sessions/{session_id}/live-run")
def get_live_run(
    tenant_id: UUID,
    session_id: UUID,
    request: Request,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_database_session),
):
    """The Run of this session that is generating now, or 204 when none is.

    Lets the client attach to a stream when it opens a session without scanning the Run list. The marker is
    held on the event channel (Redis / memory) or, on the database backend, read from the Run table.
    """
    sessions.get_session_for_user(db, principal, tenant_id, session_id)
    marker = get_run_channels(request).marker
    run_id = marker.get(session_id)
    if run_id is None:
        return Response(status_code=204)
    run = runs.get_run(db, principal, tenant_id, UUID(run_id))
    return {"run_id": str(run.id), "status": run.status}


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
        # Release this request's connection now: the stream below opens short sessions of its own, so a
        # viewer waiting for the next event holds no database connection and no worker thread.
        db.close()
        factory = request.app.state.session_factory
        channels = get_run_channels(request)

        def page(after: int, size: int):
            with factory() as session:
                run = runs.get_run(session, principal, tenant_id, run_id)
                rows = runs.list_events(session, principal, tenant_id, run_id, after, size)
                return [BusEvent(str(row.run_id), row.event_type, row.payload, row.sequence,
                                 row.occurred_at.isoformat(), str(row.sequence)) for row in rows], run.status

        def current_status() -> str:
            with factory() as session:
                return runs.get_run(session, principal, tenant_id, run_id).status

        async def stream():
            heartbeat = ': heartbeat\n\n'
            async for item in stream_run_events(channels, run_id, cursor, page, current_status):
                if item.kind == 'heartbeat':
                    yield heartbeat
                elif item.kind == 'resync':
                    yield 'event: stream.resync\ndata: {}\n\n'
                elif item.kind == 'closed':
                    yield 'event: stream.closed\ndata: {}\n\n'
                elif item.event.sequence is None:
                    # Unsequenced text carries no SSE id, so Last-Event-ID always names a stored event.
                    data = RunEventView(event_id=uuid4(), run_id=run_id, sequence=item.cursor, event_type=item.event.kind,
                        schema_version=1, payload=item.event.payload, ephemeral=True,
                        occurred_at=datetime.now(timezone.utc)).model_dump_json()
                    yield f'event: run.event\ndata: {data}\n\n'
                else:
                    event = item.event
                    data = RunEventView(event_id=uuid5(run_id, str(event.sequence)), run_id=run_id,
                        sequence=event.sequence, event_type=event.kind, schema_version=1, payload=event.payload,
                        occurred_at=event.occurred_at).model_dump_json()
                    yield f'id: {event.sequence}\nevent: run.event\ndata: {data}\n\n'
        return StreamingResponse(stream(), media_type='text/event-stream',
            headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})
    return [event_view(row) for row in runs.list_events(db, principal, tenant_id, run_id, cursor, limit)]


def event_view(row):
    return RunEventView(event_id=row.id, run_id=row.run_id, sequence=row.sequence, event_type=row.event_type,
        schema_version=row.schema_version, payload=row.payload, occurred_at=row.occurred_at)


@router.get("/tenants/{tenant_id}/runs/{run_id}/trajectory", response_model=list[RunTrajectoryRecordView])
def list_run_trajectory(
    tenant_id: UUID,
    run_id: UUID,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_database_session),
):
    """Read the independently persisted model request records after Run authorization."""
    return [trajectory_record_view(row) for row in runs.list_trajectory_records(db, principal, tenant_id, run_id)]


def trajectory_record_view(row):
    """Map a durable request snapshot to the public, read-only trajectory DTO."""
    return RunTrajectoryRecordView(id=row.id, run_id=row.run_id, sequence=row.sequence, turn=row.turn,
        attempt=row.attempt, purpose=row.purpose, status=row.status,
        input_estimate_tokens=row.input_estimate_tokens, run_total_tokens=row.run_total_tokens,
        request_snapshot=row.request_snapshot, response_snapshot=row.response_snapshot, usage=row.usage,
        error_code=row.error_code, started_at=row.started_at, completed_at=row.completed_at)


@router.post("/tenants/{tenant_id}/runs/{run_id}/watchdog/acknowledge", response_model=RunView, status_code=202)
def acknowledge_run_watchdog(
    tenant_id: UUID,
    run_id: UUID,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_database_session),
):
    """Record that the user saw a watchdog alert and keeps waiting. Does not change the Run's execution."""
    run = acknowledge_watchdog(db, principal, tenant_id, run_id)
    view = RunView.model_validate(run, from_attributes=True)
    view.attention_required = attention_required(db, run.id)
    return view


@router.post("/tenants/{tenant_id}/runs/{run_id}/cancel", response_model=RunView, status_code=202)
def cancel_run(
    tenant_id: UUID,
    run_id: UUID,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_database_session),
):
    return RunView.model_validate(runs.request_cancel(db, principal, tenant_id, run_id), from_attributes=True)


@router.get("/tenants/{tenant_id}/audit-log", response_model=list[dict[str, Any]], deprecated=True)
@tenant_admin_route(router, "/tenants/{tenant_id}/audit", methods=["GET"], response_model=list[dict[str, Any]])
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
    return TenantView(id=row.id, name=row.name, code=row.code, kind=row.kind, description=row.description, role=role,
                      status=row.status, created_at=row.created_at)


def model_profile_view(profile, version) -> ModelProfileView:
    return ModelProfileView(
        id=profile.id, tenant_id=profile.tenant_id, name=profile.name, provider=profile.provider,
        current_version=model_version_view(version) if version else None, created_at=profile.created_at,
    )


def model_version_view(row) -> ModelProfileVersionView:
    return ModelProfileVersionView.model_validate(row, from_attributes=True)


def agent_view(row, bindings, public_version=None, *, user_id: UUID | None = None, can_maintain: bool = False
               ) -> AgentView:
    """Serialize an agent: the published version when ``public_version`` is given, otherwise the draft."""
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
        ownership=row.ownership, owned_by_me=user_id is not None and row.created_by == user_id,
        can_maintain=can_maintain, created_at=row.created_at, updated_at=row.updated_at,
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
                          'content': row.content, 'created_at': row.created_at,
                          # Knowledge citations resolved when the Run completed (openspec 2026-11-06-knowledge-base).
                          'citations': row.runtime_metadata.get('citations', [])} for row in messages],
            'latest_run': RunView.model_validate(latest, from_attributes=True) if latest else None,
            # Set when a lost worker left this session blocked; the client offers to release it.
            'blocked': unknown_runs.blocked_by(db, session_id, side_effects_by_name())}


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
    """Offer a builtin tool in this space (kept for existing clients).

    Builtin tools are registered under the system space and assignable in every space without this call; it now
    only lifts a switch-off the space made earlier and returns the registration an agent binds.
    """
    from nexus_core.platform import SYSTEM_TENANT_ID
    from nexus_tools.builtins import builtins
    from nexus_platform.errors import NotFound
    from nexus_platform.persistence.models import TenantBuiltinDisabledRecord
    from nexus_platform.system import ensure_system_tenant, sync_builtin_tools
    tool = builtins().get(name, 'v1')
    if not tool:
        raise NotFound('Tool not found')
    with db.begin():
        user = resolve_user(db, principal)
        require_tenant(db, tenant_id)
        require_membership(db, tenant_id, user.id)
        require_api_permission(db, tenant_id, user.id, "tools:manage")
        ensure_system_tenant(db)
        sync_builtin_tools(db)
        off = db.get(TenantBuiltinDisabledRecord, (tenant_id, 'tool', name))
        if off is not None:
            db.delete(off)
        audit(db, tenant_id, user.id, 'tool.enabled', 'tool', name)
    return {'kind': 'tool', 'resource_id': name, 'resource_version_id': 'v1', 'source_tenant_id': SYSTEM_TENANT_ID}


@router.get('/tenants/{tenant_id}/builtin-disabled')
def list_builtin_disabled(tenant_id: UUID, principal: Principal = Depends(get_principal),
                          db: Session = Depends(get_database_session)):
    """Builtin skills and tools this space has switched off."""
    from nexus_platform import system
    return system.list_disabled(db, principal, tenant_id)


@router.put('/tenants/{tenant_id}/builtin-disabled/{kind}/{resource_id}')
def disable_builtin_resource(tenant_id: UUID, kind: str, resource_id: str, principal: Principal = Depends(get_principal),
                             db: Session = Depends(get_database_session)):
    """Stop offering one builtin skill or tool in this space (needs ``tools:manage``)."""
    from nexus_platform import system
    return system.disable_builtin(db, principal, tenant_id, kind, resource_id)


@router.delete('/tenants/{tenant_id}/builtin-disabled/{kind}/{resource_id}')
def enable_builtin_resource(tenant_id: UUID, kind: str, resource_id: str, principal: Principal = Depends(get_principal),
                            db: Session = Depends(get_database_session)):
    """Offer a switched-off builtin skill or tool in this space again."""
    from nexus_platform import system
    return system.enable_builtin_resource(db, principal, tenant_id, kind, resource_id)
