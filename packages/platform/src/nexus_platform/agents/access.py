"""Agent-level authorization: who may view, run, edit, publish or manage one agent.

Access to an agent is granted when the caller is an owner or admin of the tenant, is the agent's
creator, or holds a role whose agent grants (expanded through the implication rules in
`authz/catalog.py`) include the requested permission. Owners, admins and creators keep the
access they had before roles existed. Missing view access reports NotFound so agents are not
revealed; other denials report Forbidden.
"""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus_core.platform import Principal, TenantRole
from nexus_platform.authz.audit import audit
from nexus_platform.authz.catalog import AGENT_PERMISSIONS, expand_agent_permissions, validate_agent_permissions
from nexus_platform.errors import Forbidden, NotFound
from nexus_platform.identity.service import require_membership, require_tenant, resolve_user
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


def agent_permissions(session: Session, tenant_id: UUID, user_id: UUID, agent: AgentRecord) -> frozenset[str]:
    """Return the effective agent permissions of an active member for one agent."""
    membership = session.get(MembershipRecord, (tenant_id, user_id))
    if membership is None or membership.status != "active":
        return frozenset()
    if membership.role in FULL_ROLES or agent.created_by == user_id:
        return AGENT_PERMISSIONS
    role_ids = select(TenantUserRoleRecord.role_id).where(
        TenantUserRoleRecord.tenant_id == tenant_id, TenantUserRoleRecord.user_id == user_id
    )
    granted = set(session.scalars(
        select(TenantAgentGrantRecord.permission).where(
            TenantAgentGrantRecord.tenant_id == tenant_id,
            TenantAgentGrantRecord.agent_id == agent.id,
            TenantAgentGrantRecord.role_id.in_(role_ids),
        )
    ))
    return expand_agent_permissions(granted)


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
    membership = session.get(MembershipRecord, (tenant_id, user_id))
    if membership is None or membership.status != "active":
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
    visible |= set(session.scalars(
        select(AgentRecord.id).where(AgentRecord.tenant_id == tenant_id, AgentRecord.created_by == user_id)
    ))
    return visible


def set_agent_grants(
    session: Session, principal: Principal, tenant_id: UUID, role_id: UUID, agent_id: UUID, permissions
) -> frozenset[str]:
    """Replace one role's grants on one agent. The actor must hold each permission it grants."""
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
    "agent_permissions", "require_agent_permission", "require_agent_access_for_principal",
    "set_agent_grants", "visible_agent_ids",
]
