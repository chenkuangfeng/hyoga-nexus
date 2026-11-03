"""Shared spaces: groups that spaces (enterprise or personal) join to share resources (openspec 2026-11-03, section 4).

Model:

- A shared space is created by one space (its `owner_tenant_id`), whose owner or admin acts for it.
- Spaces join a shared space, not people. Each member space has one role there: `admin`, `editor` or `viewer`.
  The owner space is always `admin` and cannot leave; it can only delete the shared space.
- Acting for a shared space uses the caller's current space (`X-Tenant-ID`). The caller must be an
  owner or admin of that space, and the space must be a member with the role the action needs.
- Entry rules: an invite code (valid for `invite_code_validity_days`), a join request, or a direct join when
  the space is searchable and does not require approval. `require_approval` turns direct joins into requests.
- Role changes and joins go through `shared_space_join_requests` (`join` or `upgrade`), which is kept apart
  from `space_join_requests` (people joining a space).

Membership rules (role limits, approval) do not change any space or resource permission by themselves; sharing
of resources is decided where resources are shared (see the knowledge and agent grants).
"""
from __future__ import annotations

import secrets
from datetime import timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from nexus_core.platform import Principal, new_id, utc_now
from nexus_platform.auth.sessions import aware
from nexus_platform.authz.audit import audit
from nexus_platform.errors import Conflict, Forbidden, NotFound
from nexus_platform.identity.service import require_membership, require_tenant, resolve_user
from nexus_platform.orgs.access import is_space_manager
from nexus_platform.persistence.models import (
    MembershipRecord,
    SharedSpaceJoinRequestRecord,
    SharedSpaceRecord,
    SharedSpaceTenantMemberRecord,
    TenantRecord,
    UserRecord,
)

ROLES = frozenset({"admin", "editor", "viewer"})
PENDING = "pending"


# ---- helpers -------------------------------------------------------------------------------------

def _acting_space(session: Session, principal: Principal, tenant_id: UUID) -> UserRecord:
    """The caller, who must be an owner or admin of the space they act for."""
    actor = resolve_user(session, principal)
    require_tenant(session, tenant_id)
    require_membership(session, tenant_id, actor.id)
    if not is_space_manager(session, tenant_id, actor.id):
        raise Forbidden("Only a space owner or admin can act for a shared space")
    return actor


def _shared(session: Session, shared_id: UUID) -> SharedSpaceRecord:
    row = session.get(SharedSpaceRecord, shared_id)
    if row is None or row.deleted_at is not None:
        raise NotFound("Shared space not found")
    return row


def _member(session: Session, shared_id: UUID, tenant_id: UUID) -> SharedSpaceTenantMemberRecord | None:
    return session.get(SharedSpaceTenantMemberRecord, (shared_id, tenant_id))


def _require_member(session: Session, shared_id: UUID, tenant_id: UUID) -> SharedSpaceTenantMemberRecord:
    row = _member(session, shared_id, tenant_id)
    if row is None:
        raise NotFound("Shared space not found")
    return row


def _require_shared_admin(session: Session, shared_id: UUID, tenant_id: UUID) -> SharedSpaceTenantMemberRecord:
    row = _member(session, shared_id, tenant_id)
    if row is None or row.role != "admin":
        raise Forbidden("Your space needs the admin role in this shared space")
    return row


def _member_count(session: Session, shared_id: UUID) -> int:
    return session.scalar(select(func.count()).select_from(SharedSpaceTenantMemberRecord).where(
        SharedSpaceTenantMemberRecord.shared_space_id == shared_id)) or 0


def _check_role(role: str) -> str:
    if role not in ROLES:
        raise ValueError("Role must be admin, editor or viewer")
    return role


def _new_invite_code(session: Session, row: SharedSpaceRecord) -> str:
    code = secrets.token_hex(6)
    row.invite_code = code
    row.invite_code_expires_at = utc_now() + timedelta(days=row.invite_code_validity_days)
    return code


def _active_invite(row: SharedSpaceRecord) -> bool:
    return bool(row.invite_code) and row.invite_code_expires_at is not None and aware(row.invite_code_expires_at) > utc_now()


def _add_member(session: Session, shared: SharedSpaceRecord, tenant_id: UUID, role: str, user_id: UUID | None) -> None:
    if _member_count(session, shared.id) >= shared.member_limit:
        raise Conflict("The shared space has reached its member limit")
    now = utc_now()
    session.add(SharedSpaceTenantMemberRecord(
        shared_space_id=shared.id, tenant_id=tenant_id, role=role, representative_user_id=user_id,
        created_at=now, updated_at=now,
    ))
    session.flush()


def _open_request(session: Session, shared: SharedSpaceRecord, tenant_id: UUID, user_id: UUID, *,
                  request_type: str, requested_role: str, message: str, prev_role: str | None) -> SharedSpaceJoinRequestRecord:
    if session.scalar(select(SharedSpaceJoinRequestRecord.id).where(
        SharedSpaceJoinRequestRecord.shared_space_id == shared.id,
        SharedSpaceJoinRequestRecord.tenant_id == tenant_id,
        SharedSpaceJoinRequestRecord.request_type == request_type,
        SharedSpaceJoinRequestRecord.status == PENDING).limit(1)) is not None:
        raise Conflict("A request of this kind is already pending for your space")
    now = utc_now()
    row = SharedSpaceJoinRequestRecord(
        id=new_id(), shared_space_id=shared.id, tenant_id=tenant_id, user_id=user_id,
        request_type=request_type, prev_role=prev_role, requested_role=requested_role, status=PENDING,
        message=message.strip() or None, created_at=now, updated_at=now,
    )
    session.add(row)
    session.flush()
    return row


def _join(session: Session, principal: Principal, tenant_id: UUID, shared: SharedSpaceRecord, *,
          via: str, message: str = "", requested_role: str = "viewer") -> dict:
    """Join directly, or open a join request when the shared space requires approval."""
    actor = _acting_space(session, principal, tenant_id)
    if _member(session, shared.id, tenant_id) is not None:
        raise Conflict("Your space is already a member of this shared space")
    if shared.require_approval:
        row = _open_request(session, shared, tenant_id, actor.id, request_type="join",
                            requested_role=_check_role(requested_role), message=message, prev_role=None)
        audit(session, tenant_id, actor.id, "shared_space.join_requested", "shared_space", str(shared.id), {"via": via})
        return {"status": "pending", "request_id": row.id}
    _add_member(session, shared, tenant_id, "viewer", actor.id)
    audit(session, tenant_id, actor.id, "shared_space.joined", "shared_space", str(shared.id), {"via": via})
    return {"status": "joined", "shared_space_id": shared.id, "role": "viewer"}


# ---- create, list, find ----------------------------------------------------------------------------

def create_shared_space(session: Session, principal: Principal, tenant_id: UUID, *, name: str,
                        description: str = "") -> SharedSpaceRecord:
    name = name.strip()
    if not name or len(name) > 160:
        raise ValueError("Shared space name must be 1-160 characters")
    now = utc_now()
    with session.begin():
        actor = _acting_space(session, principal, tenant_id)
        row = SharedSpaceRecord(
            id=new_id(), name=name, description=description.strip() or None, owner_user_id=actor.id,
            owner_tenant_id=tenant_id, created_at=now, updated_at=now,
        )
        session.add(row)
        session.flush()
        session.add(SharedSpaceTenantMemberRecord(
            shared_space_id=row.id, tenant_id=tenant_id, role="admin", representative_user_id=actor.id,
            created_at=now, updated_at=now,
        ))
        audit(session, tenant_id, actor.id, "shared_space.created", "shared_space", str(row.id), {"name": name})
    return row


def list_shared_spaces(session: Session, principal: Principal, tenant_id: UUID) -> list[dict]:
    """Shared spaces the acting space belongs to, with its role and the member count."""
    with session.begin():
        actor = resolve_user(session, principal)
        require_tenant(session, tenant_id)
        require_membership(session, tenant_id, actor.id)
        rows = session.execute(
            select(SharedSpaceRecord, SharedSpaceTenantMemberRecord.role)
            .join(SharedSpaceTenantMemberRecord, SharedSpaceTenantMemberRecord.shared_space_id == SharedSpaceRecord.id)
            .where(SharedSpaceTenantMemberRecord.tenant_id == tenant_id, SharedSpaceRecord.deleted_at.is_(None))
            .order_by(SharedSpaceRecord.created_at)
        ).all()
        return [_summary(session, shared, role) for shared, role in rows]


def search_shared_spaces(session: Session, principal: Principal, query: str) -> list[dict]:
    """Searchable shared spaces whose name contains the query. Shows no membership data."""
    needle = (query or "").strip().lower()
    with session.begin():
        resolve_user(session, principal)
        rows = session.scalars(select(SharedSpaceRecord).where(
            SharedSpaceRecord.searchable.is_(True), SharedSpaceRecord.deleted_at.is_(None))
            .order_by(SharedSpaceRecord.name).limit(50)).all()
        return [{"id": row.id, "name": row.name, "description": row.description,
                 "member_count": _member_count(session, row.id)} for row in rows if needle in row.name.lower()]


def preview_by_code(session: Session, principal: Principal, code: str) -> dict:
    """What an invite code leads to, before joining. The code must be current."""
    with session.begin():
        resolve_user(session, principal)
        row = session.scalar(select(SharedSpaceRecord).where(SharedSpaceRecord.invite_code == code.strip()))
        if row is None or row.deleted_at is not None or not _active_invite(row):
            raise NotFound("Invite code is invalid or has expired")
        return {"id": row.id, "name": row.name, "description": row.description,
                "member_count": _member_count(session, row.id), "require_approval": row.require_approval}


def get_shared_space(session: Session, principal: Principal, tenant_id: UUID, shared_id: UUID) -> dict:
    """Detail for a member space: settings, its own role, and every member space with its role."""
    with session.begin():
        actor = resolve_user(session, principal)
        require_tenant(session, tenant_id)
        require_membership(session, tenant_id, actor.id)
        row = _shared(session, shared_id)
        mine = _require_member(session, shared_id, tenant_id)
        members = session.execute(
            select(SharedSpaceTenantMemberRecord, TenantRecord.name)
            .join(TenantRecord, TenantRecord.id == SharedSpaceTenantMemberRecord.tenant_id)
            .where(SharedSpaceTenantMemberRecord.shared_space_id == shared_id)
            .order_by(TenantRecord.name)).all()
        detail = _summary(session, row, mine.role)
        detail.update({
            "require_approval": row.require_approval, "searchable": row.searchable,
            "member_limit": row.member_limit, "invite_code_validity_days": row.invite_code_validity_days,
            "members": [{"tenant_id": m.tenant_id, "tenant_name": name, "role": m.role} for m, name in members],
        })
        if mine.role == "admin":
            detail["invite_code"] = row.invite_code if _active_invite(row) else None
        return detail


def update_shared_space(session: Session, principal: Principal, tenant_id: UUID, shared_id: UUID, **fields) -> SharedSpaceRecord:
    """Change name, description, approval, searchability, member limit or invite validity. Shared-space admins only."""
    now = utc_now()
    with session.begin():
        actor = _acting_space(session, principal, tenant_id)
        row = _shared(session, shared_id)
        _require_shared_admin(session, shared_id, tenant_id)
        if fields.get("name") is not None:
            name = fields["name"].strip()
            if not name or len(name) > 160:
                raise ValueError("Shared space name must be 1-160 characters")
            row.name = name
        if fields.get("description") is not None:
            row.description = fields["description"].strip() or None
        for flag in ("require_approval", "searchable"):
            if fields.get(flag) is not None:
                setattr(row, flag, bool(fields[flag]))
        if fields.get("member_limit") is not None:
            if fields["member_limit"] < _member_count(session, shared_id):
                raise Conflict("The member limit cannot be below the current member count")
            row.member_limit = fields["member_limit"]
        if fields.get("invite_code_validity_days") is not None:
            row.invite_code_validity_days = fields["invite_code_validity_days"]
        row.updated_at = now
        audit(session, tenant_id, actor.id, "shared_space.updated", "shared_space", str(shared_id),
              {k: v for k, v in fields.items() if v is not None})
    return row


def delete_shared_space(session: Session, principal: Principal, tenant_id: UUID, shared_id: UUID) -> None:
    """Only the space that created the shared space may delete it. Deletion is soft."""
    now = utc_now()
    with session.begin():
        actor = _acting_space(session, principal, tenant_id)
        row = _shared(session, shared_id)
        if row.owner_tenant_id != tenant_id:
            raise Forbidden("Only the creating space can delete this shared space")
        row.deleted_at, row.updated_at = now, now
        audit(session, tenant_id, actor.id, "shared_space.deleted", "shared_space", str(shared_id))


def leave_shared_space(session: Session, principal: Principal, tenant_id: UUID, shared_id: UUID) -> None:
    with session.begin():
        actor = _acting_space(session, principal, tenant_id)
        row = _shared(session, shared_id)
        if row.owner_tenant_id == tenant_id:
            raise Conflict("The creating space cannot leave; delete the shared space instead")
        _require_member(session, shared_id, tenant_id)
        session.delete(_member(session, shared_id, tenant_id))
        audit(session, tenant_id, actor.id, "shared_space.left", "shared_space", str(shared_id))


# ---- joining and changing role ----------------------------------------------------------------------

def join_by_code(session: Session, principal: Principal, tenant_id: UUID, code: str) -> dict:
    with session.begin():
        row = session.scalar(select(SharedSpaceRecord).where(SharedSpaceRecord.invite_code == code.strip()))
        if row is None or row.deleted_at is not None or not _active_invite(row):
            raise NotFound("Invite code is invalid or has expired")
        return _join(session, principal, tenant_id, row, via="invite_code")


def join_by_id(session: Session, principal: Principal, tenant_id: UUID, shared_id: UUID) -> dict:
    with session.begin():
        row = _shared(session, shared_id)
        if not row.searchable:
            raise Forbidden("This shared space is not open to direct joins")
        return _join(session, principal, tenant_id, row, via="search")


def request_join(session: Session, principal: Principal, tenant_id: UUID, shared_id: UUID, *,
                 requested_role: str, message: str = "") -> dict:
    with session.begin():
        row = _shared(session, shared_id)
        return _join(session, principal, tenant_id, row, via="request", message=message,
                     requested_role=requested_role)


def request_upgrade(session: Session, principal: Principal, tenant_id: UUID, shared_id: UUID, *,
                    requested_role: str, message: str = "") -> SharedSpaceJoinRequestRecord:
    with session.begin():
        actor = _acting_space(session, principal, tenant_id)
        row = _shared(session, shared_id)
        current = _require_member(session, shared_id, tenant_id)
        requested = _check_role(requested_role)
        if requested == current.role:
            raise Conflict("Your space already has this role")
        req = _open_request(session, row, tenant_id, actor.id, request_type="upgrade",
                            requested_role=requested, message=message, prev_role=current.role)
        audit(session, tenant_id, actor.id, "shared_space.upgrade_requested", "shared_space", str(shared_id))
    return req


def regenerate_invite_code(session: Session, principal: Principal, tenant_id: UUID, shared_id: UUID) -> dict:
    with session.begin():
        actor = _acting_space(session, principal, tenant_id)
        row = _shared(session, shared_id)
        _require_shared_admin(session, shared_id, tenant_id)
        code = _new_invite_code(session, row)
        audit(session, tenant_id, actor.id, "shared_space.invite_code_created", "shared_space", str(shared_id))
        return {"invite_code": code, "expires_at": row.invite_code_expires_at}


def list_join_requests(session: Session, principal: Principal, tenant_id: UUID, shared_id: UUID) -> list[dict]:
    with session.begin():
        _acting_space(session, principal, tenant_id)
        _shared(session, shared_id)
        _require_shared_admin(session, shared_id, tenant_id)
        rows = session.execute(
            select(SharedSpaceJoinRequestRecord, TenantRecord.name)
            .join(TenantRecord, TenantRecord.id == SharedSpaceJoinRequestRecord.tenant_id)
            .where(SharedSpaceJoinRequestRecord.shared_space_id == shared_id,
                   SharedSpaceJoinRequestRecord.status == PENDING)
            .order_by(SharedSpaceJoinRequestRecord.created_at)).all()
        return [{"id": r.id, "tenant_id": r.tenant_id, "tenant_name": name, "request_type": r.request_type,
                 "prev_role": r.prev_role, "requested_role": r.requested_role, "message": r.message,
                 "created_at": r.created_at} for r, name in rows]


def review_join_request(session: Session, principal: Principal, tenant_id: UUID, shared_id: UUID,
                        request_id: UUID, *, approve: bool, review_message: str = "") -> SharedSpaceJoinRequestRecord:
    now = utc_now()
    with session.begin():
        actor = _acting_space(session, principal, tenant_id)
        shared = _shared(session, shared_id)
        _require_shared_admin(session, shared_id, tenant_id)
        req = session.get(SharedSpaceJoinRequestRecord, request_id)
        if req is None or req.shared_space_id != shared_id:
            raise NotFound("Join request not found")
        if req.status != PENDING:
            raise Conflict("This request is no longer pending")
        if approve:
            existing = _member(session, shared_id, req.tenant_id)
            if req.request_type == "upgrade":
                if existing is None:
                    raise Conflict("The space is no longer a member")
                existing.role, existing.updated_at = req.requested_role, now
            elif existing is None:
                _add_member(session, shared, req.tenant_id, req.requested_role, req.user_id)
            else:
                raise Conflict("The space is already a member")
            req.status = "approved"
        else:
            req.status = "rejected"
        req.reviewed_by, req.review_message, req.updated_at = actor.id, review_message.strip() or None, now
        audit(session, tenant_id, actor.id, "shared_space.request_reviewed", "shared_space", str(shared_id),
              {"request_id": str(request_id), "approved": approve})
    return req


def _summary(session: Session, shared: SharedSpaceRecord, role: str | None) -> dict:
    return {"id": shared.id, "name": shared.name, "description": shared.description, "role": role,
            "owner_tenant_id": shared.owner_tenant_id, "member_count": _member_count(session, shared.id),
            "created_at": shared.created_at}
