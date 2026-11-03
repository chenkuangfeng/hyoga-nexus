"""Members, invitations and join applications of an enterprise space (openspec 2026-11-03, section 3).

Rules:

- Adding people needs `members:manage` in the space. Owners are never granted by these flows; the owner
  role is assigned only at creation of a space.
- Invitation: the space invites an existing account by email (`direction = invitation`). Accepting it
  activates the membership with the invited role and, optionally, a primary organization node. An email
  with no account gets an account only through `accounts.create_password_account` (temporary password).
- Application: a person applies to join an enterprise (`direction = application`). A rejection carries a
  reason and blocks new applications for 7 days. Approval needs an organization node and a role.
- Every write is audited in `audit_records`.
- Positions and roles never grant access by themselves; a membership is what grants the space.
"""
from __future__ import annotations

from datetime import timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus_core.platform import Principal, new_id, utc_now
from nexus_platform.auth.accounts import normalize_email
from nexus_platform.auth.sessions import aware
from nexus_platform.authz.audit import audit
from nexus_platform.authz.permissions import require_api_permission
from nexus_platform.errors import Conflict, Forbidden, NotFound
from nexus_platform.identity.service import require_membership, require_tenant, resolve_user
from nexus_platform.persistence.models import (
    MembershipRecord,
    OrgUnitRecord,
    SpaceJoinRequestRecord,
    TenantRecord,
    TenantRoleRecord,
    TenantUserRoleRecord,
    UserOrgUnitRecord,
    UserRecord,
)
from nexus_platform.tenants.service import lock_tenant

INVITABLE_ROLES = frozenset({"admin", "contributor", "viewer"})
REJECTION_COOLDOWN = timedelta(days=7)
PENDING = "pending"


# ---- helpers -------------------------------------------------------------------------------------

def _manager(session: Session, principal: Principal, tenant_id: UUID):
    """The caller, after checking the space exists and `members:manage` is granted to them."""
    actor = resolve_user(session, principal)
    require_tenant(session, tenant_id)
    require_membership(session, tenant_id, actor.id)
    require_api_permission(session, tenant_id, actor.id, "members:manage")
    return actor


def _invitable_role(role: str) -> str:
    if role not in INVITABLE_ROLES:
        raise ValueError("Role must be admin, contributor or viewer")
    return role


def _active_unit(session: Session, tenant_id: UUID, unit_id: UUID) -> OrgUnitRecord:
    unit = session.get(OrgUnitRecord, unit_id)
    if unit is None or unit.tenant_id != tenant_id:
        raise NotFound("Organization node not found")
    if unit.status != "active":
        raise Conflict("The organization node is disabled")
    return unit


def _place(session: Session, tenant_id: UUID, user_id: UUID, unit_id: UUID, now) -> None:
    """Give a member a node in the organization tree; the first node becomes primary."""
    has_primary = session.scalar(select(UserOrgUnitRecord.unit_id).where(
        UserOrgUnitRecord.tenant_id == tenant_id, UserOrgUnitRecord.user_id == user_id,
        UserOrgUnitRecord.is_primary.is_(True)).limit(1)) is not None
    session.add(UserOrgUnitRecord(tenant_id=tenant_id, user_id=user_id, unit_id=unit_id,
                                  is_primary=not has_primary, created_at=now))


def _activate(session: Session, tenant_id: UUID, user_id: UUID, role: str, source: str,
              unit_id: UUID | None, now) -> MembershipRecord:
    """Create or reactivate a membership. An active member cannot be activated again."""
    membership = session.get(MembershipRecord, (tenant_id, user_id))
    if membership is not None and membership.status == "active":
        raise Conflict("The user is already a member of this space")
    if membership is None:
        membership = MembershipRecord(tenant_id=tenant_id, user_id=user_id, role=role, status="active",
                                      source=source, joined_at=now)
        session.add(membership)
    else:
        membership.role, membership.status, membership.source = role, "active", source
        membership.joined_at, membership.revoked_at = now, None
    session.flush()
    if unit_id is not None:
        _place(session, tenant_id, user_id, unit_id, now)
    return membership


def _ensure_no_pending(session: Session, tenant_id: UUID, user_id: UUID) -> None:
    if session.scalar(select(SpaceJoinRequestRecord.id).where(
        SpaceJoinRequestRecord.tenant_id == tenant_id, SpaceJoinRequestRecord.user_id == user_id,
        SpaceJoinRequestRecord.status == PENDING).limit(1)) is not None:
        raise Conflict("A pending invitation or application already exists for this person")


def _request(session: Session, tenant_id: UUID, request_id: UUID, direction: str) -> SpaceJoinRequestRecord:
    row = session.get(SpaceJoinRequestRecord, request_id)
    if row is None or row.tenant_id != tenant_id or row.direction != direction:
        raise NotFound("Request not found")
    return row


# ---- invitations --------------------------------------------------------------------------------

def invite_existing_account(session: Session, principal: Principal, tenant_id: UUID, *, email: str,
                            role: str, unit_id: UUID | None = None) -> SpaceJoinRequestRecord | None:
    """Invite the account that has this email. Returns None when no account uses it, so the caller can
    create one instead (see `nexus_api.http.memberships`). Permissions are checked first either way."""
    address = normalize_email(email)
    role = _invitable_role(role)
    now = utc_now()
    with session.begin():
        actor = _manager(session, principal, tenant_id)
        lock_tenant(session, tenant_id)
        user = session.scalar(select(UserRecord).where(UserRecord.email == address))
        if user is None:
            return None
        if unit_id is not None:
            _active_unit(session, tenant_id, unit_id)
        membership = session.get(MembershipRecord, (tenant_id, user.id))
        if membership is not None and membership.status == "active":
            raise Conflict("The user is already a member of this space")
        _ensure_no_pending(session, tenant_id, user.id)
        row = SpaceJoinRequestRecord(
            id=new_id(), tenant_id=tenant_id, user_id=user.id, direction="invitation", status=PENDING,
            role=role, unit_id=unit_id, created_by=actor.id, created_at=now, updated_at=now,
        )
        session.add(row)
        session.flush()
        audit(session, tenant_id, actor.id, "tenant.invitation_created", "user", str(user.id), {"role": role})
    return row


def list_invitations(session: Session, principal: Principal, tenant_id: UUID) -> list[dict]:
    with session.begin():
        _manager(session, principal, tenant_id)
        rows = session.execute(
            select(SpaceJoinRequestRecord, UserRecord)
            .join(UserRecord, UserRecord.id == SpaceJoinRequestRecord.user_id)
            .where(SpaceJoinRequestRecord.tenant_id == tenant_id,
                   SpaceJoinRequestRecord.direction == "invitation",
                   SpaceJoinRequestRecord.status == PENDING)
            .order_by(SpaceJoinRequestRecord.created_at)
        ).all()
        return [_request_view(req, user) for req, user in rows]


def cancel_invitation(session: Session, principal: Principal, tenant_id: UUID, invitation_id: UUID) -> None:
    now = utc_now()
    with session.begin():
        actor = _manager(session, principal, tenant_id)
        row = _request(session, tenant_id, invitation_id, "invitation")
        if row.status != PENDING:
            raise Conflict("Only a pending invitation can be cancelled")
        row.status, row.updated_at, row.reviewed_by = "withdrawn", now, actor.id
        audit(session, tenant_id, actor.id, "tenant.invitation_cancelled", "user", str(row.user_id))


def my_invitations(session: Session, principal: Principal) -> list[dict]:
    with session.begin():
        user = resolve_user(session, principal)
        rows = session.execute(
            select(SpaceJoinRequestRecord, TenantRecord)
            .join(TenantRecord, TenantRecord.id == SpaceJoinRequestRecord.tenant_id)
            .where(SpaceJoinRequestRecord.user_id == user.id,
                   SpaceJoinRequestRecord.direction == "invitation",
                   SpaceJoinRequestRecord.status == PENDING)
            .order_by(SpaceJoinRequestRecord.created_at)
        ).all()
        return [{"id": req.id, "tenant_id": space.id, "tenant_name": space.name, "role": req.role,
                 "created_at": req.created_at} for req, space in rows]


def respond_to_invitation(session: Session, principal: Principal, invitation_id: UUID, *, accept: bool) -> dict:
    """The invitee accepts (joins the space) or declines. Only the invitee can answer."""
    now = utc_now()
    with session.begin():
        user = resolve_user(session, principal)
        row = session.get(SpaceJoinRequestRecord, invitation_id)
        if row is None or row.user_id != user.id or row.direction != "invitation":
            raise NotFound("Invitation not found")
        if row.status != PENDING:
            raise Conflict("This invitation is no longer pending")
        tenant_id = row.tenant_id
        if accept:
            lock_tenant(session, tenant_id)
            _activate(session, tenant_id, user.id, row.role, "invitation", row.unit_id, now)
            row.status = "approved"
        else:
            row.status = "rejected"
        row.updated_at, row.reviewed_by = now, user.id
        audit(session, tenant_id, user.id, "tenant.invitation_accepted" if accept else "tenant.invitation_declined",
              "user", str(user.id), {"role": row.role})
    return {"tenant_id": tenant_id, "status": row.status}


# ---- applications -------------------------------------------------------------------------------

def apply_to_join(session: Session, principal: Principal, tenant_id: UUID, message: str = "") -> SpaceJoinRequestRecord:
    """Ask to join an enterprise. Personal spaces take no applications. A rejected applicant waits 7 days."""
    now = utc_now()
    with session.begin():
        user = resolve_user(session, principal)
        space = require_tenant(session, tenant_id)
        if space.kind != "enterprise":
            raise Forbidden("Only enterprise spaces accept applications")
        membership = session.get(MembershipRecord, (tenant_id, user.id))
        if membership is not None and membership.status == "active":
            raise Conflict("You are already a member of this space")
        _ensure_no_pending(session, tenant_id, user.id)
        last = session.scalar(select(SpaceJoinRequestRecord).where(
            SpaceJoinRequestRecord.tenant_id == tenant_id, SpaceJoinRequestRecord.user_id == user.id,
            SpaceJoinRequestRecord.direction == "application", SpaceJoinRequestRecord.cooldown_until.is_not(None),
        ).order_by(SpaceJoinRequestRecord.created_at.desc()).limit(1))
        if last is not None and aware(last.cooldown_until) > now:
            raise Forbidden("Your last application was rejected; you can apply again after the cooldown")
        row = SpaceJoinRequestRecord(
            id=new_id(), tenant_id=tenant_id, user_id=user.id, direction="application", status=PENDING,
            role="contributor", unit_id=None, message=message.strip() or None, created_by=user.id,
            created_at=now, updated_at=now,
        )
        session.add(row)
        session.flush()
        audit(session, tenant_id, user.id, "tenant.application_created", "user", str(user.id))
    return row


def withdraw_application(session: Session, principal: Principal, tenant_id: UUID, application_id: UUID) -> None:
    now = utc_now()
    with session.begin():
        user = resolve_user(session, principal)
        row = _request(session, tenant_id, application_id, "application")
        if row.user_id != user.id:
            raise NotFound("Request not found")
        if row.status != PENDING:
            raise Conflict("Only a pending application can be withdrawn")
        row.status, row.updated_at = "withdrawn", now


def list_applications(session: Session, principal: Principal, tenant_id: UUID) -> list[dict]:
    with session.begin():
        _manager(session, principal, tenant_id)
        rows = session.execute(
            select(SpaceJoinRequestRecord, UserRecord)
            .join(UserRecord, UserRecord.id == SpaceJoinRequestRecord.user_id)
            .where(SpaceJoinRequestRecord.tenant_id == tenant_id,
                   SpaceJoinRequestRecord.direction == "application",
                   SpaceJoinRequestRecord.status == PENDING)
            .order_by(SpaceJoinRequestRecord.created_at)
        ).all()
        return [_request_view(req, user) for req, user in rows]


def approve_application(session: Session, principal: Principal, tenant_id: UUID, application_id: UUID, *,
                        unit_id: UUID, role: str) -> MembershipRecord:
    """Approve with a required organization node and role. The new member is recorded as `application`."""
    role = _invitable_role(role)
    now = utc_now()
    with session.begin():
        actor = _manager(session, principal, tenant_id)
        lock_tenant(session, tenant_id)
        row = _request(session, tenant_id, application_id, "application")
        if row.status != PENDING:
            raise Conflict("This application is no longer pending")
        _active_unit(session, tenant_id, unit_id)
        membership = _activate(session, tenant_id, row.user_id, role, "application", unit_id, now)
        row.status, row.role, row.unit_id = "approved", role, unit_id
        row.reviewed_by, row.updated_at = actor.id, now
        audit(session, tenant_id, actor.id, "tenant.application_approved", "user", str(row.user_id),
              {"role": role, "unit_id": str(unit_id)})
    return membership


def reject_application(session: Session, principal: Principal, tenant_id: UUID, application_id: UUID, *,
                       reason: str) -> None:
    reason = reason.strip()
    if not reason:
        raise ValueError("A rejection needs a reason")
    now = utc_now()
    with session.begin():
        actor = _manager(session, principal, tenant_id)
        row = _request(session, tenant_id, application_id, "application")
        if row.status != PENDING:
            raise Conflict("This application is no longer pending")
        row.status, row.reject_reason = "rejected", reason
        row.cooldown_until, row.reviewed_by, row.updated_at = now + REJECTION_COOLDOWN, actor.id, now
        audit(session, tenant_id, actor.id, "tenant.application_rejected", "user", str(row.user_id))


# ---- leaving and batch roles ---------------------------------------------------------------------

def leave_space(session: Session, principal: Principal, tenant_id: UUID) -> None:
    """Leave a space. The owner cannot leave; they must transfer ownership first."""
    now = utc_now()
    with session.begin():
        user = resolve_user(session, principal)
        require_tenant(session, tenant_id)
        membership = require_membership(session, tenant_id, user.id)
        if membership.role == "owner":
            raise Conflict("The owner cannot leave the space; transfer ownership first")
        membership.status, membership.revoked_at = "revoked", now
        audit(session, tenant_id, user.id, "tenant.member_left", "user", str(user.id))


def assign_role_to_unit(session: Session, principal: Principal, tenant_id: UUID, unit_id: UUID,
                        role_id: UUID) -> dict:
    """Give a custom role to every active member placed directly in one node (not its subtree).

    Owners and admins already hold the full catalog and are skipped. People who already have the role are
    skipped too, so the call can be repeated safely. Returns `assigned` and `skipped` user ids.
    """
    now = utc_now()
    with session.begin():
        actor = _manager(session, principal, tenant_id)
        lock_tenant(session, tenant_id)
        _active_unit(session, tenant_id, unit_id)
        role = session.get(TenantRoleRecord, role_id)
        if role is None or role.tenant_id != tenant_id:
            raise NotFound("Tenant role not found")
        member_ids = list(session.scalars(
            select(UserOrgUnitRecord.user_id).join(
                MembershipRecord,
                (MembershipRecord.tenant_id == UserOrgUnitRecord.tenant_id)
                & (MembershipRecord.user_id == UserOrgUnitRecord.user_id))
            .where(UserOrgUnitRecord.tenant_id == tenant_id, UserOrgUnitRecord.unit_id == unit_id,
                   MembershipRecord.status == "active", MembershipRecord.role.not_in(["owner", "admin"]))
            .distinct()))
        assigned, skipped = [], []
        for user_id in member_ids:
            if session.get(TenantUserRoleRecord, (tenant_id, user_id, role_id)) is not None:
                skipped.append(user_id)
                continue
            session.add(TenantUserRoleRecord(tenant_id=tenant_id, user_id=user_id, role_id=role_id, assigned_at=now))
            assigned.append(user_id)
        session.flush()
        audit(session, tenant_id, actor.id, "tenant.role_assigned_to_unit", "org_unit", str(unit_id),
              {"role_id": str(role_id), "assigned": len(assigned), "skipped": len(skipped)})
    return {"assigned": assigned, "skipped": skipped}


def place_member(session: Session, principal: Principal, tenant_id: UUID, user_id: UUID, unit_id: UUID) -> None:
    """Put an active member in an active node (used right after an account is created for them)."""
    now = utc_now()
    with session.begin():
        actor = _manager(session, principal, tenant_id)
        lock_tenant(session, tenant_id)
        _active_unit(session, tenant_id, unit_id)
        membership = session.get(MembershipRecord, (tenant_id, user_id))
        if membership is None or membership.status != "active":
            raise NotFound("Tenant member not found")
        if session.get(UserOrgUnitRecord, (tenant_id, user_id, unit_id)) is not None:
            raise Conflict("The member is already in this node")
        _place(session, tenant_id, user_id, unit_id, now)
        audit(session, tenant_id, actor.id, "tenant.member_placed", "user", str(user_id), {"unit_id": str(unit_id)})


# ---- views --------------------------------------------------------------------------------------

def _request_view(req: SpaceJoinRequestRecord, user: UserRecord) -> dict:
    return {
        "id": req.id, "user_id": user.id, "display_name": user.display_name, "email": user.email,
        "role": req.role, "unit_id": req.unit_id, "message": req.message, "status": req.status,
        "created_at": req.created_at,
    }


__all__ = [
    "approve_application", "apply_to_join", "assign_role_to_unit", "cancel_invitation", "invite_existing_account",
    "leave_space", "place_member", "list_applications", "list_invitations", "my_invitations", "reject_application",
    "respond_to_invitation", "withdraw_application",
]
