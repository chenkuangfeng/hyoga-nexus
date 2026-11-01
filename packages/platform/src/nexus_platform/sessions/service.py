from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from nexus_core.platform import Principal, new_id, utc_now
from nexus_platform.errors import Forbidden, NotFound
from nexus_platform.models.provider_settings import authorize_model
from nexus_platform.agents.access import require_agent_permission
from nexus_platform.identity.service import require_membership, require_tenant, resolve_user
from nexus_platform.orgs.access import SOURCE_ORGANIZATION, is_space_manager, organization_unit_for, subtree_ids
from nexus_platform.persistence.models import AgentRecord, AgentVersionRecord, MembershipRecord, SessionRecord


def create_session(
    session: Session, principal: Principal, tenant_id: UUID, *, agent_version_id: UUID, title: str = ""
) -> SessionRecord:
    now = utc_now()
    with session.begin():
        user = resolve_user(session, principal)
        require_tenant(session, tenant_id)
        require_membership(session, tenant_id, user.id)
        row = session.execute(
            select(AgentRecord, AgentVersionRecord)
            .join(AgentVersionRecord, AgentVersionRecord.agent_id == AgentRecord.id)
            .where(
                AgentRecord.tenant_id == tenant_id,
                AgentVersionRecord.id == agent_version_id,
                AgentRecord.published_version_id == agent_version_id,
            )
        ).first()
        if row is None:
            raise NotFound("Published agent version not found")
        agent_version = row[1]
        require_agent_permission(session, tenant_id, user.id, row[0], "run")
        authorize_model(session, tenant_id, user.id, agent_version.model_profile_version_id)
        membership = session.get(MembershipRecord, (tenant_id, user.id))
        # Snapshot the organization node only for people who came through an organization.
        org_unit_id = organization_unit_for(session, tenant_id, user.id) if membership.source == SOURCE_ORGANIZATION else None
        created = SessionRecord(
            id=new_id(), tenant_id=tenant_id, owner_user_id=user.id, org_unit_id=org_unit_id,
            agent_version_id=agent_version.id, runtime_type=agent_version.runtime_type,
            title=title.strip(), status="active", created_at=now, updated_at=now,
        )
        session.add(created)
    return created


def list_sessions(session: Session, principal: Principal, tenant_id: UUID) -> list[SessionRecord]:
    with session.begin():
        user = resolve_user(session, principal)
        require_tenant(session, tenant_id)
        require_membership(session, tenant_id, user.id)
        query = select(SessionRecord).where(SessionRecord.tenant_id == tenant_id)
        # Owners and admins see every session in their space; everyone else sees only their own.
        if not is_space_manager(session, tenant_id, user.id):
            query = query.where(SessionRecord.owner_user_id == user.id)
        return list(session.scalars(query.order_by(SessionRecord.updated_at.desc())))


def list_sessions_for_platform_admin(
    session: Session, principal: Principal, *, tenant_id: UUID | None = None,
    agent_id: UUID | None = None, org_unit_id: UUID | None = None, limit: int = 200,
) -> list[SessionRecord]:
    """Sessions across all spaces for a platform administrator, optionally filtered.

    `agent_id` matches the agent behind the session's version; `org_unit_id` matches the session's
    organization snapshot and everything under that node. Non-administrators get Forbidden.
    """
    with session.begin():
        user = resolve_user(session, principal)
        if not user.is_platform_admin:
            raise Forbidden("Platform administrator required")
        query = select(SessionRecord)
        if tenant_id is not None:
            query = query.where(SessionRecord.tenant_id == tenant_id)
        if agent_id is not None:
            query = query.join(AgentVersionRecord, AgentVersionRecord.id == SessionRecord.agent_version_id).where(
                AgentVersionRecord.agent_id == agent_id)
        if org_unit_id is not None:
            query = query.where(SessionRecord.org_unit_id.in_(subtree_ids(session, org_unit_id)))
        return list(session.scalars(query.order_by(SessionRecord.updated_at.desc()).limit(limit)))


def get_session_for_user(session: Session, principal: Principal, tenant_id: UUID, session_id: UUID):
    with session.begin():
        user = resolve_user(session, principal)
        require_tenant(session, tenant_id)
        require_membership(session, tenant_id, user.id)
        query = select(SessionRecord).where(SessionRecord.id == session_id, SessionRecord.tenant_id == tenant_id)
        if not is_space_manager(session, tenant_id, user.id):
            query = query.where(SessionRecord.owner_user_id == user.id)
        row = session.scalar(query)
        if row is None:
            raise NotFound("Session not found")
        return row


def conversation(session, principal, tenant_id, session_id, *, after_sequence=0, limit=200):
    from nexus_platform.persistence.models import MessageRecord, RunRecord
    owner = get_session_for_user(session, principal, tenant_id, session_id)
    with session.begin():
        messages = list(session.scalars(select(MessageRecord).where(
            MessageRecord.session_id == owner.id, MessageRecord.sequence > after_sequence)
            .order_by(MessageRecord.sequence).limit(limit)))
        latest = session.scalar(select(RunRecord).where(RunRecord.session_id == owner.id)
                                .order_by(RunRecord.created_at.desc()).limit(1))
        return messages, latest
