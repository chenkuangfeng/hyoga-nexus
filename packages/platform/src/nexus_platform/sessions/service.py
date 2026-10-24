from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from nexus_core.platform import Principal, new_id, utc_now
from nexus_platform.errors import NotFound
from nexus_platform.identity.service import require_membership, require_workspace, resolve_user
from nexus_platform.persistence.models import AgentRecord, AgentVersionRecord, SessionRecord


def create_session(
    session: Session, principal: Principal, workspace_id: UUID, *, agent_version_id: UUID, title: str = ""
) -> SessionRecord:
    now = utc_now()
    with session.begin():
        user = resolve_user(session, principal)
        require_workspace(session, workspace_id)
        require_membership(session, workspace_id, user.id)
        row = session.execute(
            select(AgentRecord, AgentVersionRecord)
            .join(AgentVersionRecord, AgentVersionRecord.agent_id == AgentRecord.id)
            .where(
                AgentRecord.workspace_id == workspace_id,
                AgentVersionRecord.id == agent_version_id,
                AgentRecord.published_version_id == agent_version_id,
            )
        ).first()
        if row is None:
            raise NotFound("Published agent version not found")
        agent_version = row[1]
        created = SessionRecord(
            id=new_id(), workspace_id=workspace_id, owner_user_id=user.id,
            agent_version_id=agent_version.id, runtime_type=agent_version.runtime_type,
            title=title.strip(), status="active", created_at=now, updated_at=now,
        )
        session.add(created)
    return created


def list_sessions(session: Session, principal: Principal, workspace_id: UUID) -> list[SessionRecord]:
    with session.begin():
        user = resolve_user(session, principal)
        require_workspace(session, workspace_id)
        require_membership(session, workspace_id, user.id)
        return list(
            session.scalars(
                select(SessionRecord)
                .where(SessionRecord.workspace_id == workspace_id, SessionRecord.owner_user_id == user.id)
                .order_by(SessionRecord.updated_at.desc())
            )
        )


def get_session_for_user(session: Session, principal: Principal, workspace_id: UUID, session_id: UUID):
    with session.begin():
        user = resolve_user(session, principal)
        require_workspace(session, workspace_id)
        require_membership(session, workspace_id, user.id)
        row = session.scalar(
            select(SessionRecord).where(
                SessionRecord.id == session_id,
                SessionRecord.workspace_id == workspace_id,
                SessionRecord.owner_user_id == user.id,
            )
        )
        if row is None:
            raise NotFound("Session not found")
        return row


def conversation(session, principal, workspace_id, session_id, *, after_sequence=0, limit=200):
    from nexus_platform.persistence.models import MessageRecord, RunRecord
    owner = get_session_for_user(session, principal, workspace_id, session_id)
    with session.begin():
        messages = list(session.scalars(select(MessageRecord).where(
            MessageRecord.session_id == owner.id, MessageRecord.sequence > after_sequence)
            .order_by(MessageRecord.sequence).limit(limit)))
        latest = session.scalar(select(RunRecord).where(RunRecord.session_id == owner.id)
                                .order_by(RunRecord.created_at.desc()).limit(1))
        return messages, latest
