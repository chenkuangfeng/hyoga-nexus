"""Organization trees, person-to-node membership, space bindings and the organization view of a space.

Rules (openspec 2026-11-01-user-org-management):

- Only a platform admin (`users.is_platform_admin`) manages trees, people in trees and bindings.
  Removing a binding is also allowed to the owner of the bound space.
- A tree is one organization. Nodes below the root are subsidiaries or departments; depth is not
  limited. Moving a node below its own subtree is rejected, so the structure stays a tree.
- A user may sit in several nodes but has exactly one primary node. Setting a new primary clears
  the old one in the same transaction; the partial unique index enforces it in the database.
- A space sees every bound node's subtree: its structure and the distinct people in it. Seeing a
  person here does not make that person a space member; joining is an explicit action
  (`add_members_from_organization`) that needs `members:manage` and a person inside a bound subtree.
- Organization audit rows go to `org_audit_records`; binding changes are also audited in the space.
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from nexus_core.platform import Principal, TenantRole, new_id, utc_now
from nexus_platform.auth.accounts import PASSWORD_PROVIDER, normalize_username
from nexus_platform.authz.audit import audit
from nexus_platform.authz.permissions import require_api_permission
from nexus_platform.errors import Conflict, Forbidden, NotFound
from nexus_platform.identity.service import require_membership, require_tenant, resolve_user
from nexus_platform.persistence.models import (
    MembershipRecord,
    OrgAuditRecord,
    OrgUnitRecord,
    TenantOrgBindingRecord,
    UserIdentityRecord,
    UserOrgUnitRecord,
    UserRecord,
)
from nexus_platform.tenants.service import lock_tenant

UNIT_STATUSES = frozenset({"active", "disabled"})


# ---- helpers -------------------------------------------------------------------------------------

def _clean_name(value: str) -> str:
    name = (value or "").strip()
    if not name or len(name) > 160:
        raise ValueError("Node name must be 1-160 characters")
    return name


def _platform_admin(session: Session, principal: Principal) -> UserRecord:
    user = resolve_user(session, principal)
    if not user.is_platform_admin:
        raise Forbidden("Organization management requires a platform administrator")
    return user


def _unit(session: Session, unit_id: UUID) -> OrgUnitRecord:
    unit = session.get(OrgUnitRecord, unit_id)
    if unit is None:
        raise NotFound("Organization node not found")
    return unit


def _lock_tree(session: Session, root_id: UUID) -> None:
    """Serialize structural edits to one tree (row lock on PostgreSQL; SQLite serializes writers)."""
    session.scalar(select(OrgUnitRecord.id).where(OrgUnitRecord.id == root_id).with_for_update())


def _check_sibling_name(session: Session, parent_id: UUID | None, name: str, *, exclude: UUID | None = None) -> None:
    """Sibling names are unique. Roots (parent NULL) are checked here because NULLs never collide in an index."""
    query = select(OrgUnitRecord.id).where(OrgUnitRecord.name == name)
    query = query.where(OrgUnitRecord.parent_id.is_(None)) if parent_id is None else query.where(
        OrgUnitRecord.parent_id == parent_id)
    if exclude is not None:
        query = query.where(OrgUnitRecord.id != exclude)
    if session.scalar(query.limit(1)) is not None:
        raise Conflict("A node with this name already exists here")


def subtree_ids(session: Session, unit_id: UUID) -> set[UUID]:
    """Ids of a node and all its descendants, via a recursive CTE (works on SQLite and PostgreSQL)."""
    base = select(OrgUnitRecord.id).where(OrgUnitRecord.id == unit_id).cte("subtree", recursive=True)
    step = select(OrgUnitRecord.id).join(base, OrgUnitRecord.parent_id == base.c.id)
    return set(session.scalars(select(base.union_all(step).c.id)))


def _audit_org(session: Session, root_id: UUID, actor_id: UUID, action: str, target_type: str,
               target_id: str, metadata: dict | None = None) -> None:
    session.add(OrgAuditRecord(
        id=new_id(), root_id=root_id, actor_user_id=actor_id, action=action, target_type=target_type,
        target_id=target_id, metadata_json=metadata or {}, created_at=utc_now(),
    ))


# ---- tree --------------------------------------------------------------------------------------

def create_organization(session: Session, principal: Principal, name: str) -> OrgUnitRecord:
    """Create a new tree whose root is the organization (group) itself."""
    name = _clean_name(name)
    now = utc_now()
    with session.begin():
        actor = _platform_admin(session, principal)
        _check_sibling_name(session, None, name)
        root_id = new_id()
        root = OrgUnitRecord(id=root_id, root_id=root_id, parent_id=None, name=name, status="active",
                             created_at=now, updated_at=now)
        session.add(root)
        session.flush()
        _audit_org(session, root.id, actor.id, "org.created", "org_unit", str(root.id), {"name": name})
    return root


def list_organizations(session: Session, principal: Principal) -> list[OrgUnitRecord]:
    with session.begin():
        _platform_admin(session, principal)
        return list(session.scalars(
            select(OrgUnitRecord).where(OrgUnitRecord.id == OrgUnitRecord.root_id).order_by(OrgUnitRecord.created_at)
        ))


def organization_tree(session: Session, principal: Principal, root_id: UUID) -> list[dict]:
    """Every node of one tree with its direct member count. Platform admin only."""
    with session.begin():
        _platform_admin(session, principal)
        root = _unit(session, root_id)
        if root.root_id != root.id:
            raise NotFound("Organization not found")
        nodes = list(session.scalars(select(OrgUnitRecord).where(OrgUnitRecord.root_id == root_id)
                                     .order_by(OrgUnitRecord.name)))
        counts = dict(session.execute(
            select(UserOrgUnitRecord.unit_id, func.count()).join(
                OrgUnitRecord, OrgUnitRecord.id == UserOrgUnitRecord.unit_id)
            .where(OrgUnitRecord.root_id == root_id).group_by(UserOrgUnitRecord.unit_id)
        ).all())
        return [{"id": n.id, "parent_id": n.parent_id, "name": n.name, "status": n.status,
                 "member_count": counts.get(n.id, 0)} for n in nodes]


def create_unit(session: Session, principal: Principal, parent_id: UUID, name: str) -> OrgUnitRecord:
    """Add a subsidiary or department below an active node."""
    name = _clean_name(name)
    now = utc_now()
    with session.begin():
        actor = _platform_admin(session, principal)
        parent = _unit(session, parent_id)
        if parent.status != "active":
            raise Conflict("The parent node is disabled")
        _lock_tree(session, parent.root_id)
        _check_sibling_name(session, parent.id, name)
        unit = OrgUnitRecord(id=new_id(), root_id=parent.root_id, parent_id=parent.id, name=name,
                             status="active", created_at=now, updated_at=now)
        session.add(unit)
        session.flush()
        _audit_org(session, parent.root_id, actor.id, "org.unit_created", "org_unit", str(unit.id),
                   {"parent_id": str(parent.id), "name": name})
    return unit


def update_unit(session: Session, principal: Principal, unit_id: UUID, *, name: str | None = None,
                parent_id: UUID | None = None, status: str | None = None) -> OrgUnitRecord:
    """Rename, move or enable/disable a node. A root cannot be moved; moves stay within one tree."""
    now = utc_now()
    with session.begin():
        actor = _platform_admin(session, principal)
        unit = _unit(session, unit_id)
        _lock_tree(session, unit.root_id)
        changes: dict[str, object] = {}
        if name is not None:
            name = _clean_name(name)
            _check_sibling_name(session, unit.parent_id, name, exclude=unit.id)
            changes["name"] = name
        if parent_id is not None and parent_id != unit.parent_id:
            if unit.parent_id is None:
                raise Conflict("An organization root cannot be moved")
            target = _unit(session, parent_id)
            if target.root_id != unit.root_id:
                raise Conflict("A node can only move within its own organization")
            if target.status != "active":
                raise Conflict("The target node is disabled")
            if target.id in subtree_ids(session, unit.id):
                raise Conflict("A node cannot be moved below its own subtree")
            _check_sibling_name(session, target.id, name or unit.name, exclude=unit.id)
            changes["parent_id"] = str(target.id)
            unit.parent_id = target.id
        if status is not None:
            if status not in UNIT_STATUSES:
                raise ValueError("Node status must be active or disabled")
            changes["status"] = status
            unit.status = status
        if name is not None:
            unit.name = name
        if changes:
            unit.updated_at = now
            _audit_org(session, unit.root_id, actor.id, "org.unit_updated", "org_unit", str(unit.id), changes)
    return unit


def delete_unit(session: Session, principal: Principal, unit_id: UUID) -> None:
    """Delete a node only when it has no children, no people and no space bindings."""
    with session.begin():
        actor = _platform_admin(session, principal)
        unit = _unit(session, unit_id)
        _lock_tree(session, unit.root_id)
        has_child = session.scalar(select(OrgUnitRecord.id).where(OrgUnitRecord.parent_id == unit.id).limit(1))
        has_member = session.scalar(select(UserOrgUnitRecord.unit_id).where(UserOrgUnitRecord.unit_id == unit.id).limit(1))
        has_binding = session.scalar(select(TenantOrgBindingRecord.unit_id).where(
            TenantOrgBindingRecord.unit_id == unit.id).limit(1))
        if has_child or has_member or has_binding:
            raise Conflict("Remove children, members and space bindings before deleting this node")
        root_id = unit.root_id
        session.delete(unit)
        session.flush()
        _audit_org(session, root_id, actor.id, "org.unit_deleted", "org_unit", str(unit_id))


# ---- people ------------------------------------------------------------------------------------

def assign_member(session: Session, principal: Principal, unit_id: UUID, user_id: UUID,
                  *, is_primary: bool = False) -> UserOrgUnitRecord:
    """Put a user into a node. The user's first node becomes primary automatically."""
    now = utc_now()
    with session.begin():
        actor = _platform_admin(session, principal)
        unit = _unit(session, unit_id)
        if unit.status != "active":
            raise Conflict("The node is disabled")
        user = session.get(UserRecord, user_id)
        if user is None or user.status != "active":
            raise NotFound("User not found")
        _lock_tree(session, unit.root_id)
        current_primary = session.scalar(select(UserOrgUnitRecord.unit_id).where(
            UserOrgUnitRecord.user_id == user_id, UserOrgUnitRecord.is_primary.is_(True)))
        make_primary = is_primary or current_primary is None
        if make_primary and current_primary is not None and current_primary != unit_id:
            session.execute(update(UserOrgUnitRecord).where(
                UserOrgUnitRecord.user_id == user_id, UserOrgUnitRecord.is_primary.is_(True)
            ).values(is_primary=False))
            session.flush()
        row = session.get(UserOrgUnitRecord, (user_id, unit_id))
        if row is None:
            row = UserOrgUnitRecord(user_id=user_id, unit_id=unit_id, is_primary=make_primary, created_at=now)
            session.add(row)
        else:
            row.is_primary = make_primary
        session.flush()
        _audit_org(session, unit.root_id, actor.id, "org.member_assigned", "user", str(user_id),
                   {"unit_id": str(unit_id), "is_primary": make_primary})
    return row


def unassign_member(session: Session, principal: Principal, unit_id: UUID, user_id: UUID) -> None:
    """Remove a user from a node. A primary node can only be removed after another primary is chosen."""
    with session.begin():
        actor = _platform_admin(session, principal)
        unit = _unit(session, unit_id)
        row = session.get(UserOrgUnitRecord, (user_id, unit_id))
        if row is None:
            raise NotFound("The user is not in this node")
        if row.is_primary:
            others = session.scalar(select(func.count()).select_from(UserOrgUnitRecord).where(
                UserOrgUnitRecord.user_id == user_id, UserOrgUnitRecord.unit_id != unit_id))
            if others:
                raise Conflict("Choose another primary node before removing this one")
        session.delete(row)
        session.flush()
        _audit_org(session, unit.root_id, actor.id, "org.member_unassigned", "user", str(user_id),
                   {"unit_id": str(unit_id)})


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


# ---- space bindings ----------------------------------------------------------------------------

def bind_space(session: Session, principal: Principal, tenant_id: UUID, unit_id: UUID) -> TenantOrgBindingRecord:
    """A platform admin binds a space to a node (its subtree becomes visible in the space)."""
    now = utc_now()
    with session.begin():
        actor = _platform_admin(session, principal)
        require_tenant(session, tenant_id)
        unit = _unit(session, unit_id)
        if unit.status != "active":
            raise Conflict("The node is disabled")
        if session.get(TenantOrgBindingRecord, (tenant_id, unit_id)) is not None:
            raise Conflict("The space is already bound to this node")
        binding = TenantOrgBindingRecord(tenant_id=tenant_id, unit_id=unit_id, created_by=actor.id, created_at=now)
        session.add(binding)
        session.flush()
        metadata = {"unit_id": str(unit_id), "root_id": str(unit.root_id)}
        audit(session, tenant_id, actor.id, "tenant.org_bound", "org_unit", str(unit_id), metadata)
        _audit_org(session, unit.root_id, actor.id, "org.space_bound", "tenant", str(tenant_id), metadata)
    return binding


def unbind_space(session: Session, principal: Principal, tenant_id: UUID, unit_id: UUID) -> None:
    """Remove a binding. Allowed to a platform admin or to the space's owner."""
    with session.begin():
        actor = resolve_user(session, principal)
        require_tenant(session, tenant_id)
        if not actor.is_platform_admin:
            require_membership(session, tenant_id, actor.id, roles={TenantRole.OWNER.value})
        binding = session.get(TenantOrgBindingRecord, (tenant_id, unit_id))
        if binding is None:
            raise NotFound("Organization binding not found")
        root_id = _unit(session, unit_id).root_id
        session.delete(binding)
        session.flush()
        metadata = {"unit_id": str(unit_id), "root_id": str(root_id)}
        audit(session, tenant_id, actor.id, "tenant.org_unbound", "org_unit", str(unit_id), metadata)
        _audit_org(session, root_id, actor.id, "org.space_unbound", "tenant", str(tenant_id), metadata)


def space_organization(session: Session, principal: Principal, tenant_id: UUID) -> dict:
    """What a space member sees: each bound node with its subtree, and the distinct people under them."""
    with session.begin():
        actor = resolve_user(session, principal)
        require_membership(session, tenant_id, actor.id)
        bindings = session.execute(
            select(TenantOrgBindingRecord, OrgUnitRecord).join(
                OrgUnitRecord, OrgUnitRecord.id == TenantOrgBindingRecord.unit_id)
            .where(TenantOrgBindingRecord.tenant_id == tenant_id)
            .order_by(OrgUnitRecord.name)
        ).all()
        result_bindings = []
        all_ids: set[UUID] = set()
        for _, unit in bindings:
            ids = subtree_ids(session, unit.id)
            all_ids |= ids
            root = _unit(session, unit.root_id)
            nodes = list(session.scalars(select(OrgUnitRecord).where(OrgUnitRecord.id.in_(ids)).order_by(OrgUnitRecord.name)))
            result_bindings.append({
                "unit_id": unit.id, "unit_name": unit.name, "organization_name": root.name, "status": unit.status,
                "nodes": [{"id": n.id, "parent_id": n.parent_id, "name": n.name, "status": n.status} for n in nodes],
            })
        return {"bindings": result_bindings, "people": _people_in(session, all_ids)}


def _people_in(session: Session, unit_ids: set[UUID]) -> list[dict]:
    """Distinct users under the given nodes, with every node of theirs inside the set."""
    if not unit_ids:
        return []
    rows = session.execute(
        select(UserRecord, UserOrgUnitRecord, OrgUnitRecord)
        .join(UserOrgUnitRecord, UserOrgUnitRecord.user_id == UserRecord.id)
        .join(OrgUnitRecord, OrgUnitRecord.id == UserOrgUnitRecord.unit_id)
        .where(UserOrgUnitRecord.unit_id.in_(unit_ids), UserRecord.status == "active")
        .order_by(UserRecord.display_name, UserRecord.id)
    ).all()
    people: dict[UUID, dict] = {}
    for user, link, unit in rows:
        person = people.setdefault(user.id, {"user_id": user.id, "display_name": user.display_name, "units": []})
        person["units"].append({"unit_id": unit.id, "unit_name": unit.name, "is_primary": link.is_primary})
    return list(people.values())


def organization_people(session: Session, principal: Principal, unit_id: UUID) -> list[dict]:
    """The distinct people under one node's subtree. Platform admin only; used to pick people for a space."""
    with session.begin():
        _platform_admin(session, principal)
        _unit(session, unit_id)
        return _people_in(session, subtree_ids(session, unit_id))


def add_members_from_organization(session: Session, principal: Principal, tenant_id: UUID,
                                  user_ids: list[UUID], role: TenantRole) -> dict:
    """Explicitly add chosen people from a bound subtree to a space. Needs `members:manage`.

    Each person must sit inside a node bound to this space. Already-active members are reported,
    not changed. Owners cannot be created this way (ownership transfer is a separate action).
    """
    if role == TenantRole.OWNER:
        raise Forbidden("Owner membership must use the ownership transfer action")
    now = utc_now()
    with session.begin():
        actor = resolve_user(session, principal)
        lock_tenant(session, tenant_id)
        require_membership(session, tenant_id, actor.id)
        require_api_permission(session, tenant_id, actor.id, "members:manage")
        bound_ids: set[UUID] = set()
        for unit_id in session.scalars(select(TenantOrgBindingRecord.unit_id).where(
                TenantOrgBindingRecord.tenant_id == tenant_id)):
            bound_ids |= subtree_ids(session, unit_id)
        added: list[UUID] = []
        skipped: list[UUID] = []
        for user_id in dict.fromkeys(user_ids):
            in_bound = session.scalar(select(UserOrgUnitRecord.unit_id).where(
                UserOrgUnitRecord.user_id == user_id, UserOrgUnitRecord.unit_id.in_(bound_ids)).limit(1)) if bound_ids else None
            if in_bound is None:
                raise NotFound("User is not in an organization bound to this space")
            user = session.get(UserRecord, user_id)
            if user is None or user.status != "active":
                raise NotFound("User not found")
            membership = session.get(MembershipRecord, (tenant_id, user_id))
            if membership is not None and membership.status == "active":
                skipped.append(user_id)
                continue
            if membership is None:
                session.add(MembershipRecord(tenant_id=tenant_id, user_id=user_id, role=role.value,
                                             status="active", joined_at=now))
            else:
                membership.role, membership.status = role.value, "active"
                membership.joined_at, membership.revoked_at = now, None
            audit(session, tenant_id, actor.id, "tenant.member_added", "user", str(user_id),
                  {"role": role.value, "source": "organization"})
            added.append(user_id)
        session.flush()
    return {"added": added, "skipped": skipped}


def list_users(session: Session, principal: Principal, query: str = "", limit: int = 200) -> list[dict]:
    """Directory for pickers: active users with their password username when they have one. Platform admin only."""
    needle = (query or "").strip().lower()
    with session.begin():
        _platform_admin(session, principal)
        users = list(session.scalars(select(UserRecord).where(UserRecord.status == "active")
                                     .order_by(UserRecord.display_name, UserRecord.id).limit(limit * 4)))
        usernames = dict(session.execute(select(UserIdentityRecord.user_id, UserIdentityRecord.external_id).where(
            UserIdentityRecord.provider == PASSWORD_PROVIDER, UserIdentityRecord.scope == "")).all())
    rows = [{"user_id": u.id, "display_name": u.display_name, "username": usernames.get(u.id)} for u in users]
    if needle:
        rows = [r for r in rows if needle in (r["display_name"] or "").lower() or needle in (r["username"] or "")]
    return rows[:limit]


def unit_bindings(session: Session, principal: Principal, unit_id: UUID) -> list[dict]:
    """Spaces bound to one node (platform admin). Lets an admin see and remove bindings from the tree."""
    from nexus_platform.persistence.models import TenantRecord
    with session.begin():
        _platform_admin(session, principal)
        _unit(session, unit_id)
        rows = session.execute(
            select(TenantRecord.id, TenantRecord.name).join(
                TenantOrgBindingRecord, TenantOrgBindingRecord.tenant_id == TenantRecord.id)
            .where(TenantOrgBindingRecord.unit_id == unit_id).order_by(TenantRecord.name)
        ).all()
    return [{"tenant_id": row[0], "tenant_name": row[1]} for row in rows]
