"""Explicit model switching via traceable Session branches, preserving GA history continuity.

Unlike GA's mutable backend swap, the source Session/AgentVersion stays immutable. The
new branch records each source message ID and keeps original authorization provenance.
"""
from uuid import UUID
from sqlalchemy import select
from nexus_core.platform import new_id, utc_now
from nexus_platform.models.provider_settings import context, authorize_model
from nexus_platform.models.service import content_hash
from nexus_platform.persistence.models import (
    AgentRecord, AgentVersionRecord, ResourceBindingRecord, SessionRecord, MessageRecord, RunRecord,
)
from nexus_platform.authz.resources import authorize_resource
from nexus_platform.authz.audit import audit
from nexus_platform.errors import NotFound, Conflict


def fork(db, principal, workspace_id, session_id, model_version_id):
    """Atomically fork an owned idle conversation to an authorized model with bound resources.

    Running source sessions cannot branch mid-tool exchange. Every copied result is checked
    against current source grants, and later execution rechecks its original Run as well.
    """
    with db.begin():
        user, _ = context(db, principal, workspace_id)
        source = db.scalar(select(SessionRecord).where(SessionRecord.id == session_id,
            SessionRecord.workspace_id == workspace_id, SessionRecord.owner_user_id == user.id).with_for_update())
        if not source:
            raise NotFound('Session unavailable')
        if db.scalar(select(RunRecord.id).where(RunRecord.session_id == session_id,
                RunRecord.status.in_(['queued', 'running', 'waiting_input', 'waiting_approval']))):
            raise Conflict('Finish or cancel the active Run before branching')
        target = authorize_model(db, workspace_id, user.id, model_version_id)
        original = db.get(AgentVersionRecord, source.agent_version_id)
        bindings = list(db.scalars(select(ResourceBindingRecord).where(ResourceBindingRecord.agent_version_id == original.id)))
        for binding in bindings:
            authorize_resource(db, workspace_id, binding.kind, binding.resource_id, source_workspace_id=binding.source_workspace_id,
                resource_version_id=binding.resource_version_id, permission='use')
        now, agent_id, version_id, branch_id = utc_now(), new_id(), new_id(), new_id()
        name = original.name[:110] + ' · ' + target.model_name[:25] + ' · ' + str(agent_id)[-8:]
        agent = AgentRecord(id=agent_id, workspace_id=workspace_id, name=name, description=original.description,
            status='published', draft_runtime_type=original.runtime_type, draft_instructions=original.instructions,
            draft_model_profile_version_id=target.id, draft_budgets=original.budgets, published_version_id=None,
            version_counter=1, created_by=user.id, created_at=now, updated_at=now)
        db.add(agent); db.flush()
        version = AgentVersionRecord(id=version_id, agent_id=agent_id, workspace_id=workspace_id, version=1,
            name=name, description=original.description, runtime_type=original.runtime_type, instructions=original.instructions,
            model_profile_version_id=target.id, budgets=original.budgets,
            content_hash=content_hash({'source_agent_version': str(original.id), 'model_version': str(target.id), 'budgets': original.budgets}),
            created_by=user.id, published_at=now)
        db.add(version); db.flush(); agent.published_version_id = version.id
        for binding in bindings:
            db.add(ResourceBindingRecord(id=new_id(), agent_version_id=version_id, kind=binding.kind,
                resource_id=binding.resource_id, resource_version_id=binding.resource_version_id,
                source_workspace_id=binding.source_workspace_id, binding_config=binding.binding_config))
        branch = SessionRecord(id=branch_id, workspace_id=workspace_id, owner_user_id=user.id,
            agent_version_id=version_id, runtime_type=original.runtime_type, title=(source.title or '对话')[:200] + ' · 模型分支',
            status='active', created_at=now, updated_at=now)
        db.add(branch); db.flush()
        from nexus_platform.runs.execution import _history_allowed
        sequence = 0
        for message in db.scalars(select(MessageRecord).where(MessageRecord.session_id == source.id).order_by(MessageRecord.sequence)):
            origin_id = message.runtime_metadata.get('source_run_id') or (str(message.run_id) if message.run_id else None)
            if origin_id:
                run = db.get(RunRecord, UUID(origin_id))
                if not run or run.principal_id != user.id or not _history_allowed(db, run):
                    continue
            sequence += 1
            db.add(MessageRecord(id=new_id(), session_id=branch_id, run_id=None, sequence=sequence,
                role=message.role, content=message.content, created_at=now,
                runtime_metadata=message.runtime_metadata | {'source_session_id': str(source.id),
                    'source_message_id': str(message.id), 'source_run_id': origin_id}))
        audit(db, workspace_id, user.id, 'session.model_forked', 'session', str(branch_id),
              {'source_session_id': str(source.id), 'model_profile_version_id': str(target.id)})
        return {'id': str(branch_id), 'agent_version_id': str(version_id), 'title': branch.title}
