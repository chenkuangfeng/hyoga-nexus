"""Organization tree (机构管理) of one enterprise, and members' positions in it.

Rules (openspec 2026-11-03-enterprise-personal-spaces, section 2):

- Every enterprise owns one tree. Its root is created on demand by the first `create_unit` call without a
  parent; the root is the enterprise's top node and cannot be moved or deleted.
- Managing the tree needs the `org:manage` permission in that enterprise (owner and admin hold it through
  the built-in catalog; custom roles may be granted it). A personal space has no tree.
- Subsidiaries and departments are ordinary nodes below the root; depth is not limited. Moving a node below
  its own subtree is rejected, so the structure stays a tree.
- A member sits in several nodes but has at most one primary node per enterprise (partial unique index).
- Only active members can be placed in a node. Revoked memberships keep their positions for audit and
  restore, but they are not counted in node member counts.
- A position never grants access. Nothing in this module feeds the permission checks of spaces or shared spaces.
- Changes write `org_audit_records`, keyed by the tree's root id.
"""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from nexus_core.platform import Principal, new_id, utc_now
from nexus_platform.auth.accounts import PASSWORD_PROVIDER, normalize_username
from nexus_platform.authz.permissions import require_api_permission
from nexus_platform.errors import Conflict, NotFound
from nexus_platform.identity.service import require_membership, require_tenant, resolve_user
from nexus_platform.orgs.access import subtree_ids
from nexus_platform.persistence.models import (
    MembershipRecord,
    OrgAuditRecord,
    OrgUnitRecord,
    UserIdentityRecord,
    UserOrgUnitRecord,
    UserRecord,
)
from nexus_platform.tenants.service import lock_tenant

UNIT_STATUSES = frozenset({"active", "disabled"})


# ---- helpers -------------------------------------------------------------------------------------

def _clean_name(value: str) -> str:
    """Trim a node name. Names are 1-160 characters after trimming."""
    name = (value or "").strip()
    if not name or len(name) > 160:
        raise ValueError("Node name must be 1-160 characters")
    return name


def _manager(session: Session, principal: Principal, tenant_id: UUID) -> UserRecord:
    """Resolve the caller and require `org:manage` in the enterprise. Raises Forbidden otherwise."""
    actor = resolve_user(session, principal)
    require_tenant(session, tenant_id)
    require_membership(session, tenant_id, actor.id)
    require_api_permission(session, tenant_id, actor.id, "org:manage")
    return actor


def _unit(session: Session, tenant_id: UUID, unit_id: UUID) -> OrgUnitRecord:
    """Load a node that belongs to the enterprise. Other enterprises' nodes look like missing ones."""
    unit = session.get(OrgUnitRecord, unit_id)
    if unit is None or unit.tenant_id != tenant_id:
        raise NotFound("Organization node not found")
    return unit


def _root(session: Session, tenant_id: UUID) -> OrgUnitRecord | None:
    return session.scalar(select(OrgUnitRecord).where(
        OrgUnitRecord.tenant_id == tenant_id, OrgUnitRecord.id == OrgUnitRecord.root_id))


def _lock_tree(session: Session, tenant_id: UUID) -> None:
    """Serialize structural edits within one enterprise (row lock on PostgreSQL; SQLite serializes writers)."""
    lock_tenant(session, tenant_id)


def _check_sibling_name(session: Session, tenant_id: UUID, parent_id: UUID | None, name: str,
                        *, exclude: UUID | None = None) -> None:
    """Sibling names are unique. Roots are checked here because NULL parents never collide in an index."""
    query = select(OrgUnitRecord.id).where(OrgUnitRecord.tenant_id == tenant_id, OrgUnitRecord.name == name)
    query = query.where(OrgUnitRecord.parent_id.is_(None)) if parent_id is None else query.where(
        OrgUnitRecord.parent_id == parent_id)
    if exclude is not None:
        query = query.where(OrgUnitRecord.id != exclude)
    if session.scalar(query.limit(1)) is not None:
        raise Conflict("A node with this name already exists here")


def _audit_org(session: Session, root_id: UUID, actor_id: UUID, action: str, target_type: str,
               target_id: str, metadata: dict | None = None) -> None:
    session.add(OrgAuditRecord(
        id=new_id(), root_id=root_id, actor_user_id=actor_id, action=action, target_type=target_type,
        target_id=target_id, metadata_json=metadata or {}, created_at=utc_now(),
    ))


def _active_membership(session: Session, tenant_id: UUID, user_id: UUID) -> MembershipRecord:
    membership = session.get(MembershipRecord, (tenant_id, user_id))
    if membership is None or membership.status != "active":
        raise NotFound("Tenant member not found")
    return membership


# ---- tree --------------------------------------------------------------------------------------

def get_tree(session: Session, principal: Principal, tenant_id: UUID) -> list[dict]:
    """Every node of the enterprise's tree with its active member count. Empty when no tree exists yet."""
    with session.begin():
        _manager(session, principal, tenant_id)
        nodes = list(session.scalars(select(OrgUnitRecord).where(OrgUnitRecord.tenant_id == tenant_id)
                                     .order_by(OrgUnitRecord.name)))
        counts = dict(session.execute(
            select(UserOrgUnitRecord.unit_id, func.count()).join(
                MembershipRecord,
                (MembershipRecord.tenant_id == UserOrgUnitRecord.tenant_id)
                & (MembershipRecord.user_id == UserOrgUnitRecord.user_id))
            .where(UserOrgUnitRecord.tenant_id == tenant_id, MembershipRecord.status == "active")
            .group_by(UserOrgUnitRecord.unit_id)
        ).all())
        return [{"id": n.id, "parent_id": n.parent_id, "name": n.name, "status": n.status,
                 "source": n.source, "member_count": counts.get(n.id, 0)} for n in nodes]


def create_unit(session: Session, principal: Principal, tenant_id: UUID, name: str,
                parent_id: UUID | None = None) -> OrgUnitRecord:
    """Add a node below an active node. Without `parent_id` this creates the enterprise root, once."""
    name = _clean_name(name)
    now = utc_now()
    with session.begin():
        actor = _manager(session, principal, tenant_id)
        _lock_tree(session, tenant_id)
        if parent_id is None:
            if _root(session, tenant_id) is not None:
                raise Conflict("The enterprise already has a root node; add nodes below it")
            root_id = new_id()
            _check_sibling_name(session, tenant_id, None, name)
            unit = OrgUnitRecord(id=root_id, tenant_id=tenant_id, root_id=root_id, parent_id=None, name=name,
                                 status="active", source="manual", created_at=now, updated_at=now)
            session.add(unit)
            session.flush()
            _audit_org(session, root_id, actor.id, "org.created", "org_unit", str(root_id), {"name": name})
            return unit
        parent = _unit(session, tenant_id, parent_id)
        if parent.status != "active":
            raise Conflict("The parent node is disabled")
        _check_sibling_name(session, tenant_id, parent.id, name)
        unit = OrgUnitRecord(id=new_id(), tenant_id=tenant_id, root_id=parent.root_id, parent_id=parent.id,
                             name=name, status="active", source="manual", created_at=now, updated_at=now)
        session.add(unit)
        session.flush()
        _audit_org(session, parent.root_id, actor.id, "org.unit_created", "org_unit", str(unit.id),
                   {"parent_id": str(parent.id), "name": name})
    return unit


def update_unit(session: Session, principal: Principal, tenant_id: UUID, unit_id: UUID, *,
                name: str | None = None, parent_id: UUID | None = None,
                status: str | None = None) -> OrgUnitRecord:
    """Rename, move, or enable/disable a node. The root cannot be moved; moves stay within the tree."""
    now = utc_now()
    with session.begin():
        actor = _manager(session, principal, tenant_id)
        unit = _unit(session, tenant_id, unit_id)
        _lock_tree(session, tenant_id)
        changes: dict[str, object] = {}
        new_name = unit.name
        if name is not None:
            new_name = _clean_name(name)
        if parent_id is not None and parent_id != unit.parent_id:
            if unit.parent_id is None:
                raise Conflict("The root node of an organization cannot be moved")
            target = _unit(session, tenant_id, parent_id)
            if target.status != "active":
                raise Conflict("The target node is disabled")
            if target.id in subtree_ids(session, unit.id):
                raise Conflict("A node cannot be moved below its own subtree")
            _check_sibling_name(session, tenant_id, target.id, new_name, exclude=unit.id)
            changes["parent_id"] = str(target.id)
            unit.parent_id = target.id
        elif new_name != unit.name:
            _check_sibling_name(session, tenant_id, unit.parent_id, new_name, exclude=unit.id)
        if new_name != unit.name:
            changes["name"] = new_name
            unit.name = new_name
        if status is not None:
            if status not in UNIT_STATUSES:
                raise ValueError("Node status must be active or disabled")
            if status != unit.status:
                changes["status"] = status
                unit.status = status
        if changes:
            unit.updated_at = now
            _audit_org(session, unit.root_id, actor.id, "org.unit_updated", "org_unit", str(unit.id), changes)
    return unit


def delete_unit(session: Session, principal: Principal, tenant_id: UUID, unit_id: UUID) -> None:
    """Delete a node only when it has no children and no members (including revoked ones)."""
    with session.begin():
        actor = _manager(session, principal, tenant_id)
        unit = _unit(session, tenant_id, unit_id)
        if unit.parent_id is None:
            raise Conflict("The root node of an organization cannot be deleted")
        _lock_tree(session, tenant_id)
        has_child = session.scalar(select(OrgUnitRecord.id).where(OrgUnitRecord.parent_id == unit.id).limit(1))
        has_member = session.scalar(select(UserOrgUnitRecord.unit_id).where(
            UserOrgUnitRecord.unit_id == unit.id).limit(1))
        if has_child or has_member:
            raise Conflict("Move or remove the children and members of this node before deleting it")
        root_id = unit.root_id
        session.delete(unit)
        session.flush()
        _audit_org(session, root_id, actor.id, "org.unit_deleted", "org_unit", str(unit_id))


# ---- people ------------------------------------------------------------------------------------

def list_unit_members(session: Session, principal: Principal, tenant_id: UUID, unit_id: UUID) -> list[dict]:
    """Active members placed directly in one node, with their primary flag."""
    with session.begin():
        _manager(session, principal, tenant_id)
        _unit(session, tenant_id, unit_id)
        rows = session.execute(
            select(UserRecord, UserOrgUnitRecord)
            .join(UserOrgUnitRecord, UserOrgUnitRecord.user_id == UserRecord.id)
            .join(MembershipRecord, (MembershipRecord.tenant_id == UserOrgUnitRecord.tenant_id)
                  & (MembershipRecord.user_id == UserOrgUnitRecord.user_id))
            .where(UserOrgUnitRecord.tenant_id == tenant_id, UserOrgUnitRecord.unit_id == unit_id,
                   MembershipRecord.status == "active")
            .order_by(UserRecord.display_name, UserRecord.id)
        ).all()
        return [{"user_id": user.id, "display_name": user.display_name, "is_primary": link.is_primary}
                for user, link in rows]


def assign_member(session: Session, principal: Principal, tenant_id: UUID, unit_id: UUID, user_id: UUID,
                  *, is_primary: bool = False) -> UserOrgUnitRecord:
    """Place an active member in a node. The member's first node becomes primary automatically."""
    now = utc_now()
    with session.begin():
        actor = _manager(session, principal, tenant_id)
        unit = _unit(session, tenant_id, unit_id)
        if unit.status != "active":
            raise Conflict("The node is disabled")
        _active_membership(session, tenant_id, user_id)
        _lock_tree(session, tenant_id)
        current_primary = session.scalar(select(UserOrgUnitRecord.unit_id).where(
            UserOrgUnitRecord.tenant_id == tenant_id, UserOrgUnitRecord.user_id == user_id,
            UserOrgUnitRecord.is_primary.is_(True)))
        make_primary = is_primary or current_primary is None
        if make_primary and current_primary is not None and current_primary != unit_id:
            session.execute(update(UserOrgUnitRecord).where(
                UserOrgUnitRecord.tenant_id == tenant_id, UserOrgUnitRecord.user_id == user_id,
                UserOrgUnitRecord.is_primary.is_(True),
            ).values(is_primary=False))
            session.flush()
        row = session.get(UserOrgUnitRecord, (tenant_id, user_id, unit_id))
        if row is None:
            row = UserOrgUnitRecord(tenant_id=tenant_id, user_id=user_id, unit_id=unit_id,
                                    is_primary=make_primary, created_at=now)
            session.add(row)
        else:
            row.is_primary = make_primary
        session.flush()
        _audit_org(session, unit.root_id, actor.id, "org.member_assigned", "user", str(user_id),
                   {"unit_id": str(unit_id), "is_primary": make_primary, "tenant_id": str(tenant_id)})
    return row


def unassign_member(session: Session, principal: Principal, tenant_id: UUID, unit_id: UUID, user_id: UUID) -> None:
    """Remove a member from a node. A primary node can only be removed after another primary is chosen."""
    with session.begin():
        actor = _manager(session, principal, tenant_id)
        unit = _unit(session, tenant_id, unit_id)
        row = session.get(UserOrgUnitRecord, (tenant_id, user_id, unit_id))
        if row is None:
            raise NotFound("The member is not in this node")
        if row.is_primary:
            others = session.scalar(select(func.count()).select_from(UserOrgUnitRecord).where(
                UserOrgUnitRecord.tenant_id == tenant_id, UserOrgUnitRecord.user_id == user_id,
                UserOrgUnitRecord.unit_id != unit_id))
            if others:
                raise Conflict("Choose another primary node before removing this one")
        session.delete(row)
        session.flush()
        _audit_org(session, unit.root_id, actor.id, "org.member_unassigned", "user", str(user_id),
                   {"unit_id": str(unit_id), "tenant_id": str(tenant_id)})


def set_platform_admin(session: Session, *, username: str, enabled: bool) -> UserRecord:
    """Operator action (CLI): grant or revoke the platform admin flag for a password account."""
    name = normalize_username(username)
    with session.begin():
        identity = session.scalar(select(UserIdentityRecord).where(
            UserIdentityRecord.provider == PASSWORD_PROVIDER, UserIdentityRecord.scope == "",
            UserIdentityRecord.external_id == name))
        if identity is None:
            raise NotFound("Account not found")
        user = session.get(UserRecord, identity.user_id)
        user.is_platform_admin = enabled
    return user
