"""Agent-level authorization: who may view, run, edit, publish or manage one agent.

Maintenance follows ownership (openspec 2026-11-11-enterprise-saas, decision 2):

- a ``personal`` agent is edited, published and managed only by its creator, while still an active member;
- an ``enterprise`` agent only by members holding the ``enterprise_agents:manage`` API permission (owners and admins
  hold it by default).

Everyone else gets use permissions only: ``view`` and ``run`` assigned through role grants. Owners and admins
also see every agent and may ``manage`` (archive) someone else's personal agent as governance, but cannot edit,
publish or run it. Missing view access reports NotFound so agents are not revealed; other denials report Forbidden.
"""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus_core.platform import Principal, TenantRole
from nexus_platform.authz.audit import audit
from nexus_platform.authz.catalog import AGENT_PERMISSIONS, expand_agent_permissions, validate_agent_permissions
from nexus_platform.authz.permissions import effective_permissions
from nexus_platform.errors import Forbidden, NotFound
from nexus_platform.identity.service import require_membership, require_tenant, resolve_user
from nexus_platform.orgs.access import membership_is_active
from nexus_platform.persistence.models import (
    AgentRecord,
    MembershipRecord,
    TenantAgentGrantRecord,
    TenantRoleRecord,
    TenantUserRoleRecord,
)
from nexus_platform.tenants.roles import require_role_manager
from nexus_platform.tenants.service import lock_tenant

FULL_ROLES = {TenantRole.OWNER.value, TenantRole.ADMIN.value}
PERSONAL = "personal"
ENTERPRISE = "enterprise"
OWNERSHIPS = frozenset({PERSONAL, ENTERPRISE})
MANAGE_ENTERPRISE_AGENTS = "enterprise_agents:manage"
#: What owners and admins hold on another member's personal agent: see it and archive it, nothing else.
GOVERNANCE_PERMISSIONS = frozenset({"view", "manage"})


def _active_membership(session: Session, tenant_id: UUID, user_id: UUID) -> MembershipRecord | None:
    membership = session.get(MembershipRecord, (tenant_id, user_id))
    return membership if membership_is_active(session, membership) else None


def can_maintain_agent(session: Session, tenant_id: UUID, user_id: UUID, agent: AgentRecord) -> bool:
    """True when the user may edit, publish and manage the agent, according to its ownership."""
    if agent.tenant_id != tenant_id or _active_membership(session, tenant_id, user_id) is None:
        return False
    if agent.ownership == PERSONAL:
        return agent.created_by == user_id
    return effective_permissions(session, tenant_id, user_id).allows_api(MANAGE_ENTERPRISE_AGENTS)


def _granted(session: Session, tenant_id: UUID, user_id: UUID, agent_id: UUID) -> frozenset[str]:
    role_ids = select(TenantUserRoleRecord.role_id).where(
        TenantUserRoleRecord.tenant_id == tenant_id, TenantUserRoleRecord.user_id == user_id
    )
    return expand_agent_permissions(session.scalars(
        select(TenantAgentGrantRecord.permission).where(
            TenantAgentGrantRecord.tenant_id == tenant_id,
            TenantAgentGrantRecord.agent_id == agent_id,
            TenantAgentGrantRecord.role_id.in_(role_ids),
        )
    ))


def agent_permissions(session: Session, tenant_id: UUID, user_id: UUID, agent: AgentRecord) -> frozenset[str]:
    """Return the effective agent permissions of an active member for one agent."""
    membership = _active_membership(session, tenant_id, user_id)
    if membership is None or agent.tenant_id != tenant_id:
        return frozenset()
    if can_maintain_agent(session, tenant_id, user_id, agent):
        return AGENT_PERMISSIONS
    granted = set(_granted(session, tenant_id, user_id, agent.id))
    from nexus_platform.authz.audiences import in_agent_audience
    if in_agent_audience(session, tenant_id, user_id, agent.id):  # departments and members assigned to use it (E5)
        granted |= {"view", "run"}
    if membership.role in FULL_ROLES:
        granted |= GOVERNANCE_PERMISSIONS
    return frozenset(granted)


def can_use_agent(session: Session, tenant_id: UUID, user_id: UUID, agent: AgentRecord) -> bool:
    """True when the user may start Runs with the agent (maintainers, or a ``run`` grant)."""
    return "run" in agent_permissions(session, tenant_id, user_id, agent)


def require_agent_permission(
    session: Session, tenant_id: UUID, user_id: UUID, agent: AgentRecord, permission: str
) -> None:
    """Raise NotFound for a missing view permission and Forbidden for any other missing permission."""
    granted = agent_permissions(session, tenant_id, user_id, agent)
    if permission in granted:
        return
    if "view" not in granted:
        raise NotFound("Agent not found")
    raise Forbidden("Your tenant role does not allow this action on this agent")


def visible_agent_ids(session: Session, tenant_id: UUID, user_id: UUID) -> set[UUID] | None:
    """Return agent ids the user may view, or None when every agent is visible (owner/admin)."""
    membership = _active_membership(session, tenant_id, user_id)
    if membership is None:
        return set()
    if membership.role in FULL_ROLES:
        return None
    role_ids = select(TenantUserRoleRecord.role_id).where(
        TenantUserRoleRecord.tenant_id == tenant_id, TenantUserRoleRecord.user_id == user_id
    )
    granted_rows = session.execute(
        select(TenantAgentGrantRecord.agent_id, TenantAgentGrantRecord.permission).where(
            TenantAgentGrantRecord.tenant_id == tenant_id, TenantAgentGrantRecord.role_id.in_(role_ids)
        )
    ).all()
    by_agent: dict[UUID, set[str]] = {}
    for agent_id, permission in granted_rows:
        by_agent.setdefault(agent_id, set()).add(permission)
    visible = {agent_id for agent_id, perms in by_agent.items() if "view" in expand_agent_permissions(perms)}
    visible |= set(session.scalars(select(AgentRecord.id).where(
        AgentRecord.tenant_id == tenant_id, AgentRecord.ownership == PERSONAL, AgentRecord.created_by == user_id
    )))
    from nexus_platform.authz.audiences import agents_for
    visible |= agents_for(session, tenant_id, user_id)
    if effective_permissions(session, tenant_id, user_id).allows_api(MANAGE_ENTERPRISE_AGENTS):
        visible |= set(session.scalars(select(AgentRecord.id).where(
            AgentRecord.tenant_id == tenant_id, AgentRecord.ownership == ENTERPRISE
        )))
    return visible


def set_agent_grants(
    session: Session, principal: Principal, tenant_id: UUID, role_id: UUID, agent_id: UUID, permissions
) -> frozenset[str]:
    """Replace one role's use grants (``view``, ``run``) on one agent. The actor must hold each permission it grants,
    so owners and admins cannot hand out use of another member's personal agent."""
    permission_set = validate_agent_permissions(permissions)
    with session.begin():
        actor_id, actor_perms = require_role_manager(session, principal, tenant_id)
        lock_tenant(session, tenant_id)
        role = session.get(TenantRoleRecord, role_id)
        if role is None or role.tenant_id != tenant_id:
            raise NotFound("Tenant role not found")
        agent = session.scalar(select(AgentRecord).where(
            AgentRecord.id == agent_id, AgentRecord.tenant_id == tenant_id
        ))
        if agent is None:
            raise NotFound("Agent not found")
        actor_agent_perms = agent_permissions(session, tenant_id, actor_id, agent)
        if not permission_set <= actor_agent_perms:
            raise Forbidden("A role cannot grant agent permissions the actor does not hold")
        if permission_set:
            from nexus_platform.agents.service import check_binding_scope
            check_binding_scope(session, agent, other_users=True, broad_users=True)
        session.query(TenantAgentGrantRecord).filter(
            TenantAgentGrantRecord.role_id == role_id, TenantAgentGrantRecord.agent_id == agent_id
        ).delete()
        session.flush()
        session.add_all(
            TenantAgentGrantRecord(role_id=role_id, agent_id=agent_id, tenant_id=tenant_id, permission=p)
            for p in sorted(permission_set)
        )
        audit(session, tenant_id, actor_id, "tenant.agent_grants_updated", "agent", str(agent_id),
              {"role_id": str(role_id), "permissions": sorted(permission_set)})
    return permission_set


def require_agent_access_for_principal(
    session: Session, principal: Principal, tenant_id: UUID, agent_id: UUID, permission: str
) -> AgentRecord:
    """Resolve the principal, require membership, and check one agent permission."""
    user = resolve_user(session, principal)
    require_tenant(session, tenant_id)
    require_membership(session, tenant_id, user.id)
    agent = session.scalar(select(AgentRecord).where(AgentRecord.id == agent_id, AgentRecord.tenant_id == tenant_id))
    if agent is None:
        raise NotFound("Agent not found")
    require_agent_permission(session, tenant_id, user.id, agent, permission)
    return agent


__all__ = [
    "ENTERPRISE", "PERSONAL", "agent_permissions", "can_maintain_agent", "can_use_agent",
    "require_agent_permission", "require_agent_access_for_principal", "set_agent_grants", "visible_agent_ids",
]
