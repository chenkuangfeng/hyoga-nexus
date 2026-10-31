"""HTTP routes for tenant roles, role assignment and the caller's effective permissions.

Management routes require the `roles:manage` API permission (owner and admin hold it implicitly).
Requests and responses use the same catalog keys that the service validates.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Response, status

from nexus_core.platform import Principal
from nexus_platform.agents.access import set_agent_grants
from nexus_platform.auth import accounts
from nexus_platform.authz.catalog import API_PERMISSIONS, MENUS
from nexus_core.platform import TenantRole
from nexus_platform.tenants import roles as roles_service
from nexus_api.dependencies.platform import get_database_session, get_principal
from nexus_api.schemas.platform import (
    AgentGrantsInput, AgentGrantsView, PermissionCatalogView, PermissionsView, RoleAssignmentView, RoleGrantsInput,
    AccountCreate, AccountView, AgentGrantRowView, RoleInput, RoleView,
)

router = APIRouter(prefix="/api/v1/tenants/{tenant_id}", tags=["Tenant roles"])


def role_view(row: dict) -> RoleView:
    role = row["role"]
    return RoleView(
        id=role.id, tenant_id=role.tenant_id, name=role.name,
        menus=row["menus"], apis=row["apis"], created_at=role.created_at, updated_at=role.updated_at,
    )


@router.get("/permission-catalog", response_model=PermissionCatalogView)
def permission_catalog(tenant_id: UUID):
    return PermissionCatalogView(menus=sorted(MENUS), apis=sorted(API_PERMISSIONS))


@router.get("/me/permissions", response_model=PermissionsView)
def my_permissions(tenant_id: UUID, principal: Principal = Depends(get_principal),
                   db=Depends(get_database_session)):
    permissions = roles_service.my_permissions(db, principal, tenant_id)
    return PermissionsView(menus=sorted(permissions.menus), apis=sorted(permissions.apis))


@router.get("/roles", response_model=list[RoleView])
def list_roles(tenant_id: UUID, principal: Principal = Depends(get_principal),
               db=Depends(get_database_session)):
    return [role_view(row) for row in roles_service.list_roles(db, principal, tenant_id)]


@router.get("/role-assignments", response_model=list[RoleAssignmentView])
def list_role_assignments(tenant_id: UUID, principal: Principal = Depends(get_principal),
                          db=Depends(get_database_session)):
    return roles_service.list_assignments(db, principal, tenant_id)


@router.get("/agent-grants", response_model=list[AgentGrantRowView])
def list_agent_grants(tenant_id: UUID, principal: Principal = Depends(get_principal),
                      db=Depends(get_database_session)):
    return roles_service.list_agent_grants(db, principal, tenant_id)


@router.post("/roles", response_model=RoleView, status_code=status.HTTP_201_CREATED)
def create_role(tenant_id: UUID, body: RoleInput, principal: Principal = Depends(get_principal),
                db=Depends(get_database_session)):
    role = roles_service.create_role(db, principal, tenant_id, body.name, body.menus, body.apis)
    menus, apis = roles_service.effective_permissions_for_role(db, role.id)
    return role_view({"role": role, "menus": sorted(menus), "apis": sorted(apis)})


@router.put("/roles/{role_id}", response_model=RoleView)
def update_role(tenant_id: UUID, role_id: UUID, body: RoleGrantsInput,
                principal: Principal = Depends(get_principal), db=Depends(get_database_session)):
    role = roles_service.update_role_grants(db, principal, tenant_id, role_id, body.menus, body.apis)
    menus, apis = roles_service.effective_permissions_for_role(db, role.id)
    return role_view({"role": role, "menus": sorted(menus), "apis": sorted(apis)})


@router.put("/members/{member_id}/roles/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
def assign_role(tenant_id: UUID, member_id: UUID, role_id: UUID,
                principal: Principal = Depends(get_principal), db=Depends(get_database_session)):
    roles_service.assign_role(db, principal, tenant_id, member_id, role_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/members/{member_id}/roles/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
def unassign_role(tenant_id: UUID, member_id: UUID, role_id: UUID,
                  principal: Principal = Depends(get_principal), db=Depends(get_database_session)):
    roles_service.unassign_role(db, principal, tenant_id, member_id, role_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/roles/{role_id}/agents/{agent_id}", response_model=AgentGrantsView)
def set_role_agent_grants(tenant_id: UUID, role_id: UUID, agent_id: UUID, body: AgentGrantsInput,
                          principal: Principal = Depends(get_principal), db=Depends(get_database_session)):
    permissions = set_agent_grants(db, principal, tenant_id, role_id, agent_id, body.permissions)
    return AgentGrantsView(role_id=role_id, agent_id=agent_id, permissions=sorted(permissions))


@router.post("/accounts", response_model=AccountView, status_code=status.HTTP_201_CREATED)
def create_account(tenant_id: UUID, body: AccountCreate, principal: Principal = Depends(get_principal),
                   db=Depends(get_database_session)):
    """Create a password account for a member of this tenant (members:manage). Password is write-only."""
    user = accounts.create_password_account(
        db, principal, tenant_id, username=body.username, display_name=body.display_name,
        password=body.password, role=TenantRole(body.role),
    )
    return AccountView(user_id=user.id, username=body.username.strip().lower(), role=body.role)
