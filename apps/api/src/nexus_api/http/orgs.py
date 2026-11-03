"""HTTP routes for an enterprise's organization tree (机构管理) and members' positions in it.

Every route is scoped to one enterprise (`/api/v1/tenants/{tenant_id}/org-units`). Callers need the
`org:manage` permission in that enterprise. Personal spaces have no tree, so the routes return 404 there.
Business rules live in `nexus_platform.orgs.service`; these routes only translate shapes.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Response, status

from nexus_core.platform import Principal
from nexus_platform.orgs import service as orgs
from nexus_api.dependencies.platform import get_database_session, get_principal
from nexus_api.schemas.orgs import LinkView, MemberLink, NodeView, UnitCreate, UnitMemberView, UnitUpdate, UnitView

router = APIRouter(prefix="/api/v1/tenants/{tenant_id}/org-units", tags=["Organizations"])


def _unit_view(row) -> UnitView:
    return UnitView(id=row.id, tenant_id=row.tenant_id, root_id=row.root_id, parent_id=row.parent_id,
                    name=row.name, status=row.status, source=row.source)


@router.get("/tree", response_model=list[NodeView])
def get_tree(tenant_id: UUID, principal: Principal = Depends(get_principal), db=Depends(get_database_session)):
    return [NodeView(**row) for row in orgs.get_tree(db, principal, tenant_id)]


@router.post("", response_model=UnitView, status_code=status.HTTP_201_CREATED)
def create_unit(tenant_id: UUID, body: UnitCreate, principal: Principal = Depends(get_principal),
                db=Depends(get_database_session)):
    return _unit_view(orgs.create_unit(db, principal, tenant_id, body.name, body.parent_id))


@router.patch("/{unit_id}", response_model=UnitView)
def update_unit(tenant_id: UUID, unit_id: UUID, body: UnitUpdate, principal: Principal = Depends(get_principal),
                db=Depends(get_database_session)):
    row = orgs.update_unit(db, principal, tenant_id, unit_id, name=body.name, parent_id=body.parent_id,
                           status=body.status)
    return _unit_view(row)


@router.delete("/{unit_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_unit(tenant_id: UUID, unit_id: UUID, principal: Principal = Depends(get_principal),
                db=Depends(get_database_session)):
    orgs.delete_unit(db, principal, tenant_id, unit_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{unit_id}/members", response_model=list[UnitMemberView])
def list_members(tenant_id: UUID, unit_id: UUID, principal: Principal = Depends(get_principal),
                 db=Depends(get_database_session)):
    return [UnitMemberView(**row) for row in orgs.list_unit_members(db, principal, tenant_id, unit_id)]


@router.put("/{unit_id}/members/{user_id}", response_model=LinkView)
def assign_member(tenant_id: UUID, unit_id: UUID, user_id: UUID, body: MemberLink | None = None,
                  principal: Principal = Depends(get_principal), db=Depends(get_database_session)):
    row = orgs.assign_member(db, principal, tenant_id, unit_id, user_id,
                             is_primary=bool(body and body.is_primary))
    return LinkView(user_id=row.user_id, unit_id=row.unit_id, is_primary=row.is_primary)


@router.delete("/{unit_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def unassign_member(tenant_id: UUID, unit_id: UUID, user_id: UUID, principal: Principal = Depends(get_principal),
                    db=Depends(get_database_session)):
    orgs.unassign_member(db, principal, tenant_id, unit_id, user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
