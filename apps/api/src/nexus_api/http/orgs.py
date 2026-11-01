"""HTTP routes for organization trees, people in nodes, space bindings and joining people to a space.

Tree and people routes require a platform administrator. The space organization view is open to
members of that space; joining people from a bound subtree needs the space's `members:manage`.
Business rules live in `nexus_platform.orgs.service`; these routes only translate shapes.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel

from nexus_core.platform import Principal
from nexus_platform.orgs import service as orgs
from nexus_api.dependencies.platform import get_database_session, get_principal
from nexus_api.schemas.orgs import (
    BindingView, BoundNode, JoinFromOrganization, JoinResult, LinkView, MemberLink, NodeView, OrgCreate, OrgView,
    PersonView, SpaceOrganizationView, UnitCreate, UnitUpdate, UnitView, UnitMembership,
)

router = APIRouter(prefix="/api/v1", tags=["Organizations"])


def _org_view(row) -> OrgView:
    return OrgView(id=row.id, name=row.name, status=row.status, created_at=row.created_at)


def _unit_view(row) -> UnitView:
    return UnitView(id=row.id, root_id=row.root_id, parent_id=row.parent_id, name=row.name, status=row.status)


class UserOption(BaseModel):
    user_id: UUID
    display_name: str | None
    username: str | None


@router.get("/users", response_model=list[UserOption])
def list_users(q: str = "", principal: Principal = Depends(get_principal), db=Depends(get_database_session)):
    """Users a platform admin can place in organization nodes. Search matches name or username."""
    return [UserOption(**row) for row in orgs.list_users(db, principal, q)]


@router.post("/orgs", response_model=OrgView, status_code=status.HTTP_201_CREATED)
def create_organization(body: OrgCreate, principal: Principal = Depends(get_principal),
                        db=Depends(get_database_session)):
    return _org_view(orgs.create_organization(db, principal, body.name))


@router.get("/orgs", response_model=list[OrgView])
def list_organizations(principal: Principal = Depends(get_principal), db=Depends(get_database_session)):
    return [_org_view(row) for row in orgs.list_organizations(db, principal)]


@router.get("/orgs/{root_id}/tree", response_model=list[NodeView])
def organization_tree(root_id: UUID, principal: Principal = Depends(get_principal),
                      db=Depends(get_database_session)):
    return [NodeView(**row) for row in orgs.organization_tree(db, principal, root_id)]


@router.post("/org-units", response_model=UnitView, status_code=status.HTTP_201_CREATED)
def create_unit(body: UnitCreate, principal: Principal = Depends(get_principal),
                db=Depends(get_database_session)):
    return _unit_view(orgs.create_unit(db, principal, body.parent_id, body.name))


@router.patch("/org-units/{unit_id}", response_model=UnitView)
def update_unit(unit_id: UUID, body: UnitUpdate, principal: Principal = Depends(get_principal),
                db=Depends(get_database_session)):
    row = orgs.update_unit(db, principal, unit_id, name=body.name, parent_id=body.parent_id, status=body.status)
    return _unit_view(row)


@router.delete("/org-units/{unit_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_unit(unit_id: UUID, principal: Principal = Depends(get_principal),
                db=Depends(get_database_session)):
    orgs.delete_unit(db, principal, unit_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/org-units/{unit_id}/members/{user_id}", response_model=LinkView)
def assign_member(unit_id: UUID, user_id: UUID, body: MemberLink | None = None,
                  principal: Principal = Depends(get_principal), db=Depends(get_database_session)):
    row = orgs.assign_member(db, principal, unit_id, user_id, is_primary=bool(body and body.is_primary))
    return LinkView(user_id=row.user_id, unit_id=row.unit_id, is_primary=row.is_primary)


@router.delete("/org-units/{unit_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def unassign_member(unit_id: UUID, user_id: UUID, principal: Principal = Depends(get_principal),
                    db=Depends(get_database_session)):
    orgs.unassign_member(db, principal, unit_id, user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/org-units/{unit_id}/people", response_model=list[PersonView])
def organization_people(unit_id: UUID, principal: Principal = Depends(get_principal),
                        db=Depends(get_database_session)):
    return [PersonView(user_id=p["user_id"], display_name=p["display_name"],
                       units=[UnitMembership(**u) for u in p["units"]])
            for p in orgs.organization_people(db, principal, unit_id)]


class BoundSpace(BaseModel):
    tenant_id: UUID
    tenant_name: str


@router.get("/org-units/{unit_id}/bindings", response_model=list[BoundSpace])
def unit_bindings(unit_id: UUID, principal: Principal = Depends(get_principal), db=Depends(get_database_session)):
    return [BoundSpace(**row) for row in orgs.unit_bindings(db, principal, unit_id)]


@router.put("/tenants/{tenant_id}/organization-bindings/{unit_id}", status_code=status.HTTP_204_NO_CONTENT)
def bind_space(tenant_id: UUID, unit_id: UUID, principal: Principal = Depends(get_principal),
               db=Depends(get_database_session)):
    orgs.bind_space(db, principal, tenant_id, unit_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/tenants/{tenant_id}/organization-bindings/{unit_id}", status_code=status.HTTP_204_NO_CONTENT)
def unbind_space(tenant_id: UUID, unit_id: UUID, principal: Principal = Depends(get_principal),
                 db=Depends(get_database_session)):
    orgs.unbind_space(db, principal, tenant_id, unit_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/tenants/{tenant_id}/organization", response_model=SpaceOrganizationView)
def space_organization(tenant_id: UUID, principal: Principal = Depends(get_principal),
                       db=Depends(get_database_session)):
    data = orgs.space_organization(db, principal, tenant_id)
    return SpaceOrganizationView(
        bindings=[BindingView(**{**b, "nodes": [BoundNode(**n) for n in b["nodes"]]}) for b in data["bindings"]],
        people=[PersonView(user_id=p["user_id"], display_name=p["display_name"],
                           units=[UnitMembership(**u) for u in p["units"]]) for p in data["people"]],
    )


@router.post("/tenants/{tenant_id}/members/from-organization", response_model=JoinResult)
def join_from_organization(tenant_id: UUID, body: JoinFromOrganization,
                           principal: Principal = Depends(get_principal), db=Depends(get_database_session)):
    result = orgs.add_members_from_organization(db, principal, tenant_id, body.user_ids, body.role_ids)
    return JoinResult(**result)
