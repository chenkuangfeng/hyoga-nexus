"""Sharing an enterprise agent with a shared space, and the effective permission of members who use it.

Rules (openspec 2026-11-03, section 4; WeKnora `kbshare.go` takes the minimum of three values):

- The agent's maintainers (decision 2 of openspec 2026-11-11-enterprise-saas) share it into a shared space at a level: `viewer`, `editor` or `admin`.
  The owning space must itself be a member of that shared space.
- A member space of the shared space sees the agent only through its own active members. For each person:
  effective level = min(share level, the member space's role in the shared space, the person's own cap), where
  the cap is admin for owners and admins, editor for contributors and viewer for viewers.
- Levels map to agent permissions: viewer → view, run; editor → + edit; admin → + publish, manage.
- Managing the shares (adding, changing, removing) stays with the owning space. Members of the shared space
  only read the agent here.
- Running a shared agent needs a cross-space model and credential decision and is not enabled by this module.
"""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus_core.platform import Principal, new_id, utc_now
from nexus_platform.authz.audit import audit
from nexus_platform.authz.catalog import AGENT_PERMISSIONS
from nexus_platform.errors import Forbidden, NotFound
from nexus_platform.identity.service import require_membership, require_tenant, resolve_user
from nexus_platform.orgs.access import is_space_manager, membership_is_active
from nexus_platform.persistence.models import (
    AgentRecord,
    AgentShareRecord,
    MembershipRecord,
    SharedSpaceRecord,
    SharedSpaceTenantMemberRecord,
    TenantRecord,
)

LEVELS: tuple[str, ...] = ("viewer", "editor", "admin")
LEVEL_RANK = {level: rank for rank, level in enumerate(LEVELS, start=1)}
LEVEL_PERMISSIONS: dict[str, frozenset[str]] = {
    "viewer": frozenset({"view", "run"}),
    "editor": frozenset({"view", "run", "edit"}),
    "admin": frozenset(AGENT_PERMISSIONS),
}
# The caller's own cap, from their role in the space they act for.
SPACE_ROLE_CAP = {"owner": "admin", "admin": "admin", "contributor": "editor", "viewer": "viewer"}


def _level_or_none(value: str | None) -> str | None:
    return value if value in LEVEL_RANK else None


def _min_level(*levels: str | None) -> str | None:
    if any(level is None for level in levels):
        return None
    return min(levels, key=lambda level: LEVEL_RANK[level])


def effective_level(share_level: str, shared_role: str, caller_role: str) -> str | None:
    """min(share level, role in the shared space, caller's cap). None means no access."""
    caller_cap = SPACE_ROLE_CAP.get(caller_role)
    return _min_level(_level_or_none(share_level), _level_or_none(shared_role), _level_or_none(caller_cap))


def permissions_for(level: str | None) -> frozenset[str]:
    return LEVEL_PERMISSIONS.get(level or "", frozenset())


def _share_row_view(share: AgentShareRecord, shared: SharedSpaceRecord, owner: TenantRecord) -> dict:
    return {
        "id": share.id, "agent_id": share.agent_id, "shared_space_id": share.shared_space_id,
        "shared_space_name": shared.name, "level": share.level, "created_at": share.created_at,
        "owner_tenant_id": owner.id, "owner_tenant_name": owner.name,
    }


def _owned_agent(session: Session, tenant_id: UUID, agent_id: UUID) -> AgentRecord:
    agent = session.scalar(select(AgentRecord).where(AgentRecord.id == agent_id, AgentRecord.tenant_id == tenant_id))
    if agent is None or agent.status == "archived":
        raise NotFound("Agent not found")
    return agent


def _live_shared(session: Session, shared_id: UUID) -> SharedSpaceRecord:
    shared = session.get(SharedSpaceRecord, shared_id)
    if shared is None or shared.deleted_at is not None:
        raise NotFound("Shared space not found")
    return shared


def _require_share_actor(session: Session, principal: Principal, tenant_id: UUID, agent_id: UUID, *,
                         governance: bool) -> tuple[UUID, AgentRecord]:
    """Who may manage an agent's shares (openspec 2026-11-11-enterprise-saas decision 2).

    Sharing needs maintenance of the agent: its creator for a personal agent, ``enterprise_agents:manage`` for an
    enterprise agent. Listing and removing shares (``governance=True``) is also open to the space's owners and admins.
    """
    from nexus_platform.agents.access import can_maintain_agent
    actor = resolve_user(session, principal)
    space = require_tenant(session, tenant_id)
    if space.kind != "enterprise":
        raise NotFound("Agent sharing is available in enterprise spaces only")
    require_membership(session, tenant_id, actor.id)
    agent = _owned_agent(session, tenant_id, agent_id)
    if not (can_maintain_agent(session, tenant_id, actor.id, agent)
            or (governance and is_space_manager(session, tenant_id, actor.id))):
        raise Forbidden("Only the agent's maintainers can share it")
    return actor.id, agent


def share_agent(session: Session, principal: Principal, tenant_id: UUID, agent_id: UUID,
                shared_space_id: UUID, level: str) -> AgentShareRecord:
    """Share an agent into a shared space, or change the level of an existing share."""
    if level not in LEVEL_RANK:
        raise ValueError("Level must be viewer, editor or admin")
    now = utc_now()
    with session.begin():
        actor_id, agent = _require_share_actor(session, principal, tenant_id, agent_id, governance=False)
        shared = _live_shared(session, shared_space_id)
        if session.get(SharedSpaceTenantMemberRecord, (shared.id, tenant_id)) is None:
            raise Forbidden("Your space must be a member of the shared space before sharing agents into it")
        share = session.scalar(select(AgentShareRecord).where(
            AgentShareRecord.agent_id == agent.id, AgentShareRecord.shared_space_id == shared.id))
        if share is None:
            share = AgentShareRecord(id=new_id(), tenant_id=tenant_id, agent_id=agent.id, shared_space_id=shared.id,
                                     level=level, created_by=actor_id, created_at=now, updated_at=now)
            session.add(share)
            action = "tenant.agent_shared"
        else:
            if share.level == level:
                return share
            share.level, share.updated_at = level, now
            action = "tenant.agent_share_changed"
        session.flush()
        audit(session, tenant_id, actor_id, action, "agent", str(agent.id),
              {"shared_space_id": str(shared.id), "level": level})
    return share


def list_agent_shares(session: Session, principal: Principal, tenant_id: UUID, agent_id: UUID) -> list[dict]:
    with session.begin():
        _require_share_actor(session, principal, tenant_id, agent_id, governance=True)
        owner = session.get(TenantRecord, tenant_id)
        rows = session.execute(
            select(AgentShareRecord, SharedSpaceRecord)
            .join(SharedSpaceRecord, SharedSpaceRecord.id == AgentShareRecord.shared_space_id)
            .where(AgentShareRecord.agent_id == agent_id, SharedSpaceRecord.deleted_at.is_(None))
            .order_by(AgentShareRecord.created_at)
        ).all()
        return [_share_row_view(share, shared, owner) for share, shared in rows]


def unshare_agent(session: Session, principal: Principal, tenant_id: UUID, agent_id: UUID,
                  shared_space_id: UUID) -> None:
    with session.begin():
        actor_id, agent = _require_share_actor(session, principal, tenant_id, agent_id, governance=True)
        share = session.scalar(select(AgentShareRecord).where(
            AgentShareRecord.agent_id == agent.id, AgentShareRecord.shared_space_id == shared_space_id))
        if share is None:
            raise NotFound("This agent is not shared with that shared space")
        session.delete(share)
        audit(session, tenant_id, actor_id, "tenant.agent_unshared", "agent", str(agent.id),
              {"shared_space_id": str(shared_space_id)})


def _caller_role(session: Session, tenant_id: UUID, user_id: UUID) -> str:
    """The caller's role in the space they act for. Non-members get NotFound, as elsewhere."""
    membership = session.get(MembershipRecord, (tenant_id, user_id))
    if not membership_is_active(session, membership):
        raise NotFound("Tenant not found")
    return membership.role


def _shared_levels_for(session: Session, caller_tenant_id: UUID, user_id: UUID) -> dict[UUID, str]:
    """For each agent shared into a shared space where the caller's space is a member: the best effective level."""
    caller_role = _caller_role(session, caller_tenant_id, user_id)
    rows = session.execute(
        select(AgentShareRecord, SharedSpaceTenantMemberRecord, SharedSpaceRecord)
        .join(SharedSpaceTenantMemberRecord,
              SharedSpaceTenantMemberRecord.shared_space_id == AgentShareRecord.shared_space_id)
        .join(SharedSpaceRecord, SharedSpaceRecord.id == AgentShareRecord.shared_space_id)
        .where(SharedSpaceTenantMemberRecord.tenant_id == caller_tenant_id,
               SharedSpaceRecord.deleted_at.is_(None))
    ).all()
    best: dict[UUID, str] = {}
    for share, member, _shared in rows:
        level = effective_level(share.level, member.role, caller_role)
        if level is None:
            continue
        current = best.get(share.agent_id)
        if current is None or LEVEL_RANK[level] > LEVEL_RANK[current]:
            best[share.agent_id] = level
    return best


def list_shared_agents(session: Session, principal: Principal, caller_tenant_id: UUID) -> list[dict]:
    """Agents of other spaces that the caller may read through a shared space, with the effective level."""
    with session.begin():
        user = resolve_user(session, principal)
        require_tenant(session, caller_tenant_id)
        _caller_role(session, caller_tenant_id, user.id)
        levels = _shared_levels_for(session, caller_tenant_id, user.id)
        if not levels:
            return []
        rows = session.execute(
            select(AgentRecord, TenantRecord)
            .join(TenantRecord, TenantRecord.id == AgentRecord.tenant_id)
            .where(AgentRecord.id.in_(list(levels)), AgentRecord.status != "archived")
            .order_by(AgentRecord.name)
        ).all()
        return [_shared_agent_view(agent, owner, levels[agent.id]) for agent, owner in rows
                if owner.id != caller_tenant_id]


def get_shared_agent(session: Session, principal: Principal, caller_tenant_id: UUID, agent_id: UUID) -> dict:
    """One shared agent. Without the view permission the agent is reported as not found."""
    with session.begin():
        user = resolve_user(session, principal)
        require_tenant(session, caller_tenant_id)
        _caller_role(session, caller_tenant_id, user.id)
        level = _shared_levels_for(session, caller_tenant_id, user.id).get(agent_id)
        if level is None or "view" not in permissions_for(level):
            raise NotFound("Agent not found")
        row = session.execute(
            select(AgentRecord, TenantRecord).join(TenantRecord, TenantRecord.id == AgentRecord.tenant_id)
            .where(AgentRecord.id == agent_id, AgentRecord.status != "archived")
        ).first()
        if row is None:
            raise NotFound("Agent not found")
        return _shared_agent_view(row[0], row[1], level)


def _shared_agent_view(agent: AgentRecord, owner: TenantRecord, level: str) -> dict:
    return {
        "id": agent.id, "name": agent.name, "description": agent.description, "status": agent.status,
        "owner_tenant_id": owner.id, "owner_tenant_name": owner.name, "level": level,
        "permissions": sorted(permissions_for(level)),
    }


__all__ = [
    "LEVELS", "effective_level", "get_shared_agent", "list_agent_shares", "list_shared_agents",
    "permissions_for", "share_agent", "unshare_agent",
]
