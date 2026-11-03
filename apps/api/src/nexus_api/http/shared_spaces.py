"""HTTP routes for shared spaces (`/api/v1/shared-spaces`).

Acting for a shared space uses the caller's current space, sent as `X-Tenant-ID`. Business rules live in
`nexus_platform.shared_spaces.service`; these routes only translate shapes.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status

from nexus_core.platform import Principal
from nexus_platform.shared_spaces import service as shared
from nexus_api.dependencies.platform import get_database_session, get_principal, get_tenant_header
from nexus_api.schemas.shared_spaces import (
    InviteCodeJoin, JoinById, JoinRequestCreate, ReviewRequest, SharedSpaceCreate, SharedSpaceUpdate, UpgradeRequest,
)

router = APIRouter(prefix="/api/v1/shared-spaces", tags=["Shared spaces"])


def _current(tenant_id: UUID | None) -> UUID:
    if tenant_id is None:
        raise HTTPException(status_code=400, detail="X-Tenant-ID is required for this action")
    return tenant_id


@router.get("")
def list_shared_spaces(tenant_id: UUID | None = Depends(get_tenant_header), principal: Principal = Depends(get_principal),
                       db=Depends(get_database_session)):
    return shared.list_shared_spaces(db, principal, _current(tenant_id))


@router.post("", status_code=status.HTTP_201_CREATED)
def create_shared_space(body: SharedSpaceCreate, tenant_id: UUID | None = Depends(get_tenant_header),
                        principal: Principal = Depends(get_principal), db=Depends(get_database_session)):
    row = shared.create_shared_space(db, principal, _current(tenant_id), name=body.name, description=body.description)
    return {"id": row.id, "name": row.name, "description": row.description, "owner_tenant_id": row.owner_tenant_id}


@router.get("/search")
def search(q: str = "", principal: Principal = Depends(get_principal), db=Depends(get_database_session)):
    return shared.search_shared_spaces(db, principal, q)


@router.get("/preview/{code}")
def preview(code: str, principal: Principal = Depends(get_principal), db=Depends(get_database_session)):
    return shared.preview_by_code(db, principal, code)


@router.post("/join")
def join_by_code(body: InviteCodeJoin, tenant_id: UUID | None = Depends(get_tenant_header),
                 principal: Principal = Depends(get_principal), db=Depends(get_database_session)):
    return shared.join_by_code(db, principal, _current(tenant_id), body.invite_code)


@router.post("/join-by-id")
def join_by_id(body: JoinById, tenant_id: UUID | None = Depends(get_tenant_header),
               principal: Principal = Depends(get_principal), db=Depends(get_database_session)):
    return shared.join_by_id(db, principal, _current(tenant_id), body.shared_space_id)


@router.post("/join-request", status_code=status.HTTP_201_CREATED)
def join_request(body: JoinRequestCreate, tenant_id: UUID | None = Depends(get_tenant_header),
                 principal: Principal = Depends(get_principal), db=Depends(get_database_session)):
    return shared.request_join(db, principal, _current(tenant_id), body.shared_space_id,
                               requested_role=body.requested_role, message=body.message)


@router.get("/{shared_id}")
def get_shared_space(shared_id: UUID, tenant_id: UUID | None = Depends(get_tenant_header),
                     principal: Principal = Depends(get_principal), db=Depends(get_database_session)):
    return shared.get_shared_space(db, principal, _current(tenant_id), shared_id)


@router.put("/{shared_id}")
def update_shared_space(shared_id: UUID, body: SharedSpaceUpdate, tenant_id: UUID | None = Depends(get_tenant_header),
                        principal: Principal = Depends(get_principal), db=Depends(get_database_session)):
    row = shared.update_shared_space(db, principal, _current(tenant_id), shared_id,
                                     **body.model_dump(exclude_unset=True))
    return {"id": row.id, "name": row.name, "description": row.description,
            "require_approval": row.require_approval, "searchable": row.searchable,
            "member_limit": row.member_limit, "invite_code_validity_days": row.invite_code_validity_days}


@router.delete("/{shared_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_shared_space(shared_id: UUID, tenant_id: UUID | None = Depends(get_tenant_header),
                        principal: Principal = Depends(get_principal), db=Depends(get_database_session)):
    shared.delete_shared_space(db, principal, _current(tenant_id), shared_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{shared_id}/leave", status_code=status.HTTP_204_NO_CONTENT)
def leave_shared_space(shared_id: UUID, tenant_id: UUID | None = Depends(get_tenant_header),
                       principal: Principal = Depends(get_principal), db=Depends(get_database_session)):
    shared.leave_shared_space(db, principal, _current(tenant_id), shared_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{shared_id}/request-upgrade", status_code=status.HTTP_201_CREATED)
def request_upgrade(shared_id: UUID, body: UpgradeRequest, tenant_id: UUID | None = Depends(get_tenant_header),
                    principal: Principal = Depends(get_principal), db=Depends(get_database_session)):
    row = shared.request_upgrade(db, principal, _current(tenant_id), shared_id,
                                 requested_role=body.requested_role, message=body.message)
    return {"id": row.id, "status": row.status, "requested_role": row.requested_role}


@router.post("/{shared_id}/invite-code")
def invite_code(shared_id: UUID, tenant_id: UUID | None = Depends(get_tenant_header),
                principal: Principal = Depends(get_principal), db=Depends(get_database_session)):
    return shared.regenerate_invite_code(db, principal, _current(tenant_id), shared_id)


@router.get("/{shared_id}/join-requests")
def list_join_requests(shared_id: UUID, tenant_id: UUID | None = Depends(get_tenant_header),
                       principal: Principal = Depends(get_principal), db=Depends(get_database_session)):
    return shared.list_join_requests(db, principal, _current(tenant_id), shared_id)


@router.post("/{shared_id}/join-requests/{request_id}/approve")
def approve_request(shared_id: UUID, request_id: UUID, body: ReviewRequest,
                    tenant_id: UUID | None = Depends(get_tenant_header), principal: Principal = Depends(get_principal),
                    db=Depends(get_database_session)):
    row = shared.review_join_request(db, principal, _current(tenant_id), shared_id, request_id, approve=True,
                                     review_message=body.review_message)
    return {"id": row.id, "status": row.status}


@router.post("/{shared_id}/join-requests/{request_id}/reject")
def reject_request(shared_id: UUID, request_id: UUID, body: ReviewRequest,
                   tenant_id: UUID | None = Depends(get_tenant_header), principal: Principal = Depends(get_principal),
                   db=Depends(get_database_session)):
    row = shared.review_join_request(db, principal, _current(tenant_id), shared_id, request_id, approve=False,
                                     review_message=body.review_message)
    return {"id": row.id, "status": row.status}
