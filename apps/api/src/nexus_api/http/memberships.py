"""HTTP routes for members, invitations, join applications, leaving a space and batch roles by node.

Business rules live in `nexus_platform.tenants.membership`; these routes only translate shapes. Managing
people needs `members:manage` in the space. Invitation and application answers are open to the person
concerned only. Personal spaces take no applications.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Response, status

from nexus_core.platform import Principal, TenantRole
from nexus_platform.auth import accounts
from nexus_platform.tenants import membership as flows
from nexus_api.dependencies.platform import get_database_session, get_principal
from nexus_api.schemas.memberships import ApplicationApprove, ApplicationCreate, ApplicationReject, MemberByEmail, RoleToUnit

router = APIRouter(prefix="/api/v1", tags=["Members"])


@router.post("/tenants/{tenant_id}/members/by-email", status_code=status.HTTP_201_CREATED)
def add_member_by_email(tenant_id: UUID, body: MemberByEmail, principal: Principal = Depends(get_principal),
                        db=Depends(get_database_session)):
    """Invite an existing account by email, or create an account for a new email (admin supplies the password)."""
    invitation = flows.invite_existing_account(db, principal, tenant_id, email=body.email, role=body.role,
                                               unit_id=body.unit_id)
    if invitation is not None:
        return {"status": "invited", "invitation_id": invitation.id}
    if not body.username or not body.password:
        raise ValueError("No account uses this email; enter a username and an initial password to create one")
    user = accounts.create_password_account(
        db, principal, tenant_id, username=body.username, email=body.email, display_name=body.display_name,
        password=body.password, role=TenantRole(body.role),
    )
    if body.unit_id is not None:
        flows.place_member(db, principal, tenant_id, user.id, body.unit_id)
    return {"status": "created", "user_id": user.id}


@router.get("/tenants/{tenant_id}/invitations")
def list_invitations(tenant_id: UUID, principal: Principal = Depends(get_principal), db=Depends(get_database_session)):
    return flows.list_invitations(db, principal, tenant_id)


@router.delete("/tenants/{tenant_id}/invitations/{invitation_id}", status_code=status.HTTP_204_NO_CONTENT)
def cancel_invitation(tenant_id: UUID, invitation_id: UUID, principal: Principal = Depends(get_principal),
                      db=Depends(get_database_session)):
    flows.cancel_invitation(db, principal, tenant_id, invitation_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me/invitations")
def my_invitations(principal: Principal = Depends(get_principal), db=Depends(get_database_session)):
    return flows.my_invitations(db, principal)


@router.get("/me/invitations/pending-count")
def pending_count(principal: Principal = Depends(get_principal), db=Depends(get_database_session)):
    return {"count": len(flows.my_invitations(db, principal))}


@router.post("/me/invitations/{invitation_id}/accept")
def accept_invitation(invitation_id: UUID, principal: Principal = Depends(get_principal), db=Depends(get_database_session)):
    return flows.respond_to_invitation(db, principal, invitation_id, accept=True)


@router.post("/me/invitations/{invitation_id}/decline")
def decline_invitation(invitation_id: UUID, principal: Principal = Depends(get_principal), db=Depends(get_database_session)):
    return flows.respond_to_invitation(db, principal, invitation_id, accept=False)


@router.post("/tenants/{tenant_id}/join-requests", status_code=status.HTTP_201_CREATED)
def apply_to_join(tenant_id: UUID, body: ApplicationCreate, principal: Principal = Depends(get_principal),
                  db=Depends(get_database_session)):
    row = flows.apply_to_join(db, principal, tenant_id, body.message)
    return {"id": row.id, "status": row.status}


@router.delete("/tenants/{tenant_id}/join-requests/{application_id}", status_code=status.HTTP_204_NO_CONTENT)
def withdraw_application(tenant_id: UUID, application_id: UUID, principal: Principal = Depends(get_principal),
                         db=Depends(get_database_session)):
    flows.withdraw_application(db, principal, tenant_id, application_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/tenants/{tenant_id}/join-requests")
def list_applications(tenant_id: UUID, principal: Principal = Depends(get_principal), db=Depends(get_database_session)):
    return flows.list_applications(db, principal, tenant_id)


@router.post("/tenants/{tenant_id}/join-requests/{application_id}/approve")
def approve_application(tenant_id: UUID, application_id: UUID, body: ApplicationApprove,
                        principal: Principal = Depends(get_principal), db=Depends(get_database_session)):
    membership = flows.approve_application(db, principal, tenant_id, application_id, unit_id=body.unit_id, role=body.role)
    return {"user_id": membership.user_id, "role": membership.role, "status": membership.status}


@router.post("/tenants/{tenant_id}/join-requests/{application_id}/reject", status_code=status.HTTP_204_NO_CONTENT)
def reject_application(tenant_id: UUID, application_id: UUID, body: ApplicationReject,
                       principal: Principal = Depends(get_principal), db=Depends(get_database_session)):
    flows.reject_application(db, principal, tenant_id, application_id, reason=body.reason)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/tenants/{tenant_id}/leave", status_code=status.HTTP_204_NO_CONTENT)
def leave_space(tenant_id: UUID, principal: Principal = Depends(get_principal), db=Depends(get_database_session)):
    flows.leave_space(db, principal, tenant_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/tenants/{tenant_id}/org-units/{unit_id}/role-assignments")
def assign_role_to_unit(tenant_id: UUID, unit_id: UUID, body: RoleToUnit, principal: Principal = Depends(get_principal),
                        db=Depends(get_database_session)):
    """Give a custom role to every member placed directly in this node (repeatable; the owner is skipped)."""
    return flows.assign_role_to_unit(db, principal, tenant_id, unit_id, body.role_id)
