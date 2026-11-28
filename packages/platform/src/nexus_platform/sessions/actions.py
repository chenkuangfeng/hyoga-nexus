"""Owner-scoped chat message branching and safe transcript rewind operations.

The source transcript and immutable Run/event audit records are retained for a branch. Rewind only
cuts text-only history; it refuses to claim success when the discarded tail has execution side effects
or artifacts because this platform does not yet checkpoint and restore sandbox workspaces.
"""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from nexus_core.platform import Principal, new_id, utc_now
from nexus_platform.authz.audit import audit
from nexus_platform.errors import Conflict, NotFound
from nexus_platform.identity.service import require_membership, require_tenant, resolve_user
from nexus_platform.persistence.models import (
    ArtifactRecord, ContextSummaryRecord, MessageRecord, RunRecord, RunTrajectoryRecord,
    SessionAdmissionRecord, SessionRecord,
)

_ACTIVE_RUNS = ('queued', 'running', 'waiting_input', 'waiting_approval')


def delete_session(db: Session, principal: Principal, tenant_id: UUID, session_id: UUID) -> None:
    """Permanently delete the caller's idle conversation, Run data, and stored artifacts."""
    artifact_files = []
    with db.begin():
        user = resolve_user(db, principal)
        require_tenant(db, tenant_id)
        require_membership(db, tenant_id, user.id)
        source = db.scalar(select(SessionRecord).where(
            SessionRecord.id == session_id, SessionRecord.tenant_id == tenant_id,
            SessionRecord.owner_user_id == user.id).with_for_update())
        if source is None:
            raise NotFound('Session unavailable')
        if db.scalar(select(RunRecord.id).where(
                RunRecord.session_id == session_id, RunRecord.status.in_(_ACTIVE_RUNS)).limit(1)):
            raise Conflict('Finish or cancel the active Run before deleting this conversation')
        if db.scalar(select(SessionAdmissionRecord.seq).where(
                SessionAdmissionRecord.session_id == session_id,
                SessionAdmissionRecord.status.in_(('queued', 'started', 'unknown'))).limit(1)):
            raise Conflict('Resolve the pending Run admission before deleting this conversation')
        if db.scalar(select(ArtifactRecord.id).where(
                ArtifactRecord.session_id == session_id, ArtifactRecord.deleted_at.is_(None)).limit(1)):
            from nexus_platform.governance.retention import purge_session
            artifact_files = purge_session(db, session_id)
        # Context summaries retain source Run references and intentionally lack ON DELETE CASCADE.
        db.execute(delete(ContextSummaryRecord).where(ContextSummaryRecord.session_id == session_id))
        audit(db, tenant_id, user.id, 'session.deleted', 'session', str(session_id),
              {'title_chars': len(source.title or '')})
        db.delete(source)
    for path in artifact_files:
        path.unlink(missing_ok=True)


def fork_at_message(db: Session, principal: Principal, tenant_id: UUID, session_id: UUID,
                    message_id: UUID) -> dict[str, str]:
    """Create a same-agent branch containing owner-visible messages through `message_id`."""
    with db.begin():
        user = resolve_user(db, principal)
        require_tenant(db, tenant_id)
        require_membership(db, tenant_id, user.id)
        source = db.scalar(select(SessionRecord).where(
            SessionRecord.id == session_id, SessionRecord.tenant_id == tenant_id,
            SessionRecord.owner_user_id == user.id).with_for_update())
        if source is None:
            raise NotFound('Session unavailable')
        if db.scalar(select(RunRecord.id).where(
                RunRecord.session_id == session_id, RunRecord.status.in_(_ACTIVE_RUNS)).limit(1)):
            raise Conflict('Finish or cancel the active Run before branching')
        point = db.scalar(select(MessageRecord).where(
            MessageRecord.session_id == session_id, MessageRecord.id == message_id))
        if point is None or point.role not in ('user', 'assistant'):
            raise NotFound('Fork point unavailable')
        if point.role == 'assistant' and point.run_id:
            run = db.get(RunRecord, point.run_id)
            if run is None or run.status != 'completed':
                raise Conflict('Wait for the assistant response to finish before branching')

        now = utc_now()
        branch_id = new_id()
        title = ((source.title or '对话')[:184] + '（分支）')[:255]
        branch = SessionRecord(id=branch_id, tenant_id=tenant_id, owner_user_id=user.id,
            agent_version_id=source.agent_version_id, runtime_type=source.runtime_type,
            title=title, status='active', created_at=now, updated_at=now)
        db.add(branch)
        db.flush()

        from nexus_platform.runs.execution import _history_allowed
        rows = list(db.scalars(select(MessageRecord).where(
            MessageRecord.session_id == session_id, MessageRecord.sequence <= point.sequence)
            .order_by(MessageRecord.sequence)))
        sequence = 0
        for row in rows:
            origin_id = (row.runtime_metadata or {}).get('source_run_id') or (str(row.run_id) if row.run_id else None)
            if origin_id:
                origin = db.get(RunRecord, UUID(origin_id))
                if not origin or origin.principal_id != user.id or not _history_allowed(db, origin):
                    continue
            sequence += 1
            db.add(MessageRecord(id=new_id(), session_id=branch_id, run_id=None, sequence=sequence,
                role=row.role, content=row.content, created_at=now,
                runtime_metadata={**(row.runtime_metadata or {}), 'source_session_id': str(session_id),
                                  'source_message_id': str(row.id), 'source_run_id': origin_id}))
        audit(db, tenant_id, user.id, 'session.forked', 'session', str(branch_id),
              {'source_session_id': str(session_id), 'message_id': str(point.id)})
        return {'id': str(branch_id), 'title': title, 'source_message_id': str(point.id)}


def rewind_to_message(db: Session, principal: Principal, tenant_id: UUID, session_id: UUID,
                      message_id: UUID) -> dict[str, int | str]:
    """Cut a text-only transcript at a user/assistant message and preserve the source run audit."""
    with db.begin():
        user = resolve_user(db, principal)
        require_tenant(db, tenant_id)
        require_membership(db, tenant_id, user.id)
        source = db.scalar(select(SessionRecord).where(
            SessionRecord.id == session_id, SessionRecord.tenant_id == tenant_id,
            SessionRecord.owner_user_id == user.id).with_for_update())
        if source is None:
            raise NotFound('Session unavailable')
        if db.scalar(select(RunRecord.id).where(
                RunRecord.session_id == session_id, RunRecord.status.in_(_ACTIVE_RUNS)).limit(1)):
            raise Conflict('Finish or cancel the active Run before rewinding')
        point = db.scalar(select(MessageRecord).where(
            MessageRecord.session_id == session_id, MessageRecord.id == message_id))
        if point is None or point.role not in ('user', 'assistant'):
            raise NotFound('Rewind point unavailable')
        if point.role == 'assistant' and point.run_id:
            run = db.get(RunRecord, point.run_id)
            if run is None or run.status != 'completed':
                raise Conflict('Wait for the assistant response to finish before rewinding')

        inclusive = point.role == 'user'
        prefill = point.content if inclusive else ''
        tail_query = select(MessageRecord).where(
            MessageRecord.session_id == session_id,
            (MessageRecord.sequence >= point.sequence if inclusive else MessageRecord.sequence > point.sequence))
        tail = list(db.scalars(tail_query.order_by(MessageRecord.sequence)))
        tail_run_ids = {row.run_id for row in tail if row.run_id}
        if tail_run_ids:
            # We do not have per-message sandbox checkpoints yet. Refuse to desynchronize a workspace,
            # and refuse to hide persisted artifacts while leaving their bytes accessible.
            has_artifacts = db.scalar(select(ArtifactRecord.id).where(
                ArtifactRecord.session_id == session_id, ArtifactRecord.run_id.in_(tail_run_ids),
                ArtifactRecord.deleted_at.is_(None)).limit(1))
            records = list(db.scalars(select(RunTrajectoryRecord).where(
                RunTrajectoryRecord.run_id.in_(tail_run_ids))))
            has_tool_calls = any(
                isinstance(record.response_snapshot, dict) and record.response_snapshot.get('tool_calls')
                for record in records)
            if has_artifacts or has_tool_calls:
                raise Conflict('This transcript has tool or artifact side effects and cannot be rewound safely')

        deleted = len(tail)
        if tail:
            for row in tail:
                db.delete(row)
        source.updated_at = utc_now()
        # A checkpoint can refer to turns that are now outside the visible transcript.
        from nexus_platform.persistence.models import WorkingCheckpointRecord
        checkpoint = db.get(WorkingCheckpointRecord, session_id)
        if checkpoint is not None:
            db.delete(checkpoint)
        from nexus_platform.sessions.snapshot import advance
        advance(db, session_id)
        audit(db, tenant_id, user.id, 'session.rewound', 'session', str(session_id),
              {'message_id': str(point.id), 'deleted_messages': deleted, 'inclusive': inclusive})
        return {'deleted_messages': deleted, 'prefill': prefill,
                'message_id': str(point.id)}
