"""Durable execution preparation; model execution stays in runtimes."""
from __future__ import annotations
from nexus_platform.persistence.unit_of_work import SqlAlchemyUnitOfWork
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker
from nexus_core.platform import CredentialRef, Principal, RunStatus, utc_now
from nexus_core.runtime import ModelMessage, RuntimeFault, RuntimeOutcome, RuntimeProgress, ToolCall
from nexus_platform.errors import PlatformError
from nexus_platform.models.provider_settings import authorize_model
from nexus_platform.identity.service import principal_for_user, require_membership, require_tenant
from nexus_platform.persistence.models import (
    AgentRecord,
    AgentVersionRecord,
    CredentialReferenceRecord,
    InputRequestRecord,
    MessageRecord,
    ModelProfileRecord,
    ModelProfileVersionRecord,
    NativeRunStateRecord,
    OutboxRecord,
    ResourceBindingRecord,
    RunRecord,
    ToolInvocationRecord,
    UserRecord,
    WorkingCheckpointRecord,
    ContextSummaryRecord,
)
from nexus_platform.runs.service import append_event, transition_run
from nexus_platform.authz.audit import audit
from nexus_platform.agents.access import require_agent_permission
from .context import ExecutionContext
from .messages import _history_allowed
from .completion import _finish

def prepare_execution(factory: sessionmaker[Session], task_id: UUID, worker_id: str) -> ExecutionContext | None:
    return ExecutionPreparer(factory).prepare(task_id, worker_id)

class ExecutionPreparer:
    """Revalidate and materialize one immutable execution context in a short transaction."""

    def __init__(self, factory):
        self.factory = factory

    def prepare(self, task_id: UUID, worker_id: str) -> ExecutionContext | None:
        with SqlAlchemyUnitOfWork(self.factory) as work:
            db = work.session
            task = db.scalar(select(OutboxRecord).where(OutboxRecord.id == task_id).with_for_update())
            if not task or task.completed_at or task.lease_owner != worker_id:
                return None
            run = db.scalar(select(RunRecord).where(RunRecord.id == task.run_id).with_for_update())
            if not run or RunStatus(run.status).terminal:
                task.completed_at = utc_now()
                return None
            if task.message_type == 'run.cancel' or run.cancel_requested_at:
                # Active execution observes the durable cancellation; it owns side-effect classification.
                if run.status != 'running':
                    _finish(db, run, RuntimeOutcome('cancelled', 'cancelled'))
                task.completed_at = utc_now()
                return None
            if run.status == 'running':
                # Reclaimed execution is uncertain, never replay tools or the model turn.
                for invocation in db.scalars(select(ToolInvocationRecord).where(
                        ToolInvocationRecord.run_id == run.id, ToolInvocationRecord.status == 'running')):
                    invocation.status, invocation.error_code, invocation.ended_at = 'interrupted', 'interrupted', utc_now()
                _finish(db, run, RuntimeOutcome('interrupted', 'worker_lease_expired'))
                task.completed_at = utc_now()
                return None
            if run.status == 'waiting_input':
                pending = db.scalar(select(InputRequestRecord.id).where(
                    InputRequestRecord.run_id == run.id, InputRequestRecord.responded_at.is_(None)))
                if pending:
                    task.completed_at = utc_now()
                    return None
            try:
                user = db.get(UserRecord, run.principal_id)
                require_tenant(db, run.tenant_id)
                require_membership(db, run.tenant_id, run.principal_id)
                if not user or user.status != 'active':
                    raise RuntimeFault('run_authorization_denied')
                version = db.get(AgentVersionRecord, UUID(run.config_snapshot['agent_version_id']))
                agent_row = db.get(AgentRecord, version.agent_id)
                require_agent_permission(db, run.tenant_id, run.principal_id, agent_row, 'run')
                authorize_model(db, run.tenant_id, run.principal_id, version.model_profile_version_id)
                model = db.get(ModelProfileVersionRecord, version.model_profile_version_id)
                profile = db.get(ModelProfileRecord, model.profile_id)
                credential = None
                if model.credential_reference_id:
                    ref = db.get(CredentialReferenceRecord, model.credential_reference_id)
                    if not ref or ref.status != 'active' or ref.tenant_id != run.tenant_id:
                        raise RuntimeFault('model_credential_unavailable')
                    credential = CredentialRef(ref.id, ref.backend, ref.handle, str(run.tenant_id))
                if not _history_allowed(db, run):
                    raise RuntimeFault('run_authorization_denied')
                history = []
                allowed_runs = []
                for source in db.scalars(select(RunRecord).where(RunRecord.session_id == run.session_id)):
                    if _history_allowed(db, source):
                        allowed_runs.append(source.id)
                for message in db.scalars(select(MessageRecord).where(MessageRecord.session_id == run.session_id)
                                           .order_by(MessageRecord.sequence)):
                    if message.run_id is not None and message.run_id not in allowed_runs:
                        continue
                    metadata = message.runtime_metadata or {}
                    if metadata.get('source_run_id'):
                        source_run = db.get(RunRecord, UUID(metadata['source_run_id']))
                        if not source_run or source_run.principal_id != run.principal_id or not _history_allowed(db, source_run):
                            continue
                    history.append(ModelMessage(message.role, message.content,
                        tuple(ToolCall(**call) for call in metadata.get('tool_calls', [])), metadata.get('tool_call_id'), str(message.id)))
                summary = db.get(ContextSummaryRecord, run.session_id)
                if summary and summary.tenant_id == run.tenant_id and summary.source_run_id in allowed_runs:
                    covered = list(db.scalars(select(MessageRecord).where(MessageRecord.session_id == run.session_id, MessageRecord.sequence <= summary.through_sequence)))
                    if all(message.run_id is None or message.run_id in allowed_runs for message in covered):
                        covered_ids = {str(message.id) for message in covered}
                        history = [ModelMessage('user', summary.content), *[m for m in history if m.source_id not in covered_ids]]
                checkpoint = db.get(WorkingCheckpointRecord, run.session_id)
                system = version.instructions
                from nexus_platform.memory.service import index as memory_index
                published_index = memory_index(db, run.tenant_id, run.principal_id,
                    version.budgets.get('behavior', {}).get('project_name', ''))
                if published_index:
                    system += '\nPublished memory/SOP index (read authorized entries on demand):\n' + published_index
                if checkpoint and checkpoint.tenant_id == run.tenant_id and checkpoint.source_run_id in allowed_runs:
                    system += '\nSession working checkpoint:\n' + checkpoint.content
                    audit(db, run.tenant_id, run.principal_id, 'checkpoint.read', 'session', str(run.session_id),
                          {'run_id': str(run.id)})
                state = db.get(NativeRunStateRecord, run.id)
                if not state:
                    state = NativeRunStateRecord(run_id=run.id, progress={})
                    db.add(state)
                if version.runtime_type == 'native' and db.scalar(select(ResourceBindingRecord.id).where(
                        ResourceBindingRecord.agent_version_id == version.id, ResourceBindingRecord.kind != 'tool').limit(1)):
                    raise RuntimeFault('runtime_capability_unavailable')
                bindings = tuple((binding.resource_id, binding.resource_version_id or 'v1', str(binding.id))
                    for binding in db.scalars(select(ResourceBindingRecord).where(
                        ResourceBindingRecord.agent_version_id == version.id, ResourceBindingRecord.kind == 'tool')))
                if len({name for name, _, _ in bindings}) != len(bindings):
                    raise RuntimeFault('tool_configuration_invalid')
                audit(db, run.tenant_id, run.principal_id, 'session.context_read', 'session', str(run.session_id),
                      {'run_id': str(run.id), 'message_count': len(history)})
                transition_run(run, RunStatus.RUNNING)
                run.attempt += 1
                run.started_at = run.started_at or utc_now()
                run.lease_owner, run.lease_until = worker_id, task.lease_until
                append_event(db, run.id, 'run.started', {'status': 'running', 'attempt': run.attempt})
                return ExecutionContext(run.id, run.session_id, run.tenant_id, run.principal_id,
                    principal_for_user(db, user.id), version.runtime_type, profile.provider, model.model_name,
                    model.options, credential, (ModelMessage('system', system), *history), bindings,
                    version.budgets, RuntimeProgress(**state.progress), tuple(allowed_runs))
            except (PlatformError, RuntimeFault) as exc:
                code = exc.code if isinstance(exc, RuntimeFault) else 'run_authorization_denied'
                _finish(db, run, RuntimeOutcome('failed', code))
                task.completed_at = utc_now()
                return None
