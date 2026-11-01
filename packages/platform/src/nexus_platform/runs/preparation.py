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
    SessionRecord,
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
from nexus_platform.sessions.projection_cache import ProjectionCache
from nexus_platform.authz.audit import audit
from nexus_platform.agents.access import require_agent_permission
from .context import ExecutionContext
from .summaries import effective_summary
from .messages import histories_allowed
from .completion import _finish

#: Raw, unfiltered message rows per session. Keyed by (session_id, watermark), so a message write
#: makes the old entry unreachable without invalidation. Authorization is applied per run after the
#: lookup, never stored here.
HISTORY_CACHE = ProjectionCache(max_entries=256, idle_ttl=900.0, max_entry_bytes=256 * 1024)


def _memo_allowed(db: Session, cache: dict[UUID, bool], source: RunRecord) -> bool:
    """Return the history-authorization result for one source Run, computing it at most once per call."""
    if source.id not in cache:
        cache[source.id] = histories_allowed(db, [source])[source.id]
    return cache[source.id]


def _message_rows(db: Session, session_id: UUID) -> list[dict]:
    """Plain-data copies of a session's messages in sequence order, safe to cache."""
    return [{'id': str(message.id), 'sequence': message.sequence,
             'run_id': str(message.run_id) if message.run_id else None,
             'role': message.role, 'content': message.content, 'runtime_metadata': dict(message.runtime_metadata or {})}
            for message in db.scalars(select(MessageRecord).where(MessageRecord.session_id == session_id)
                                      .order_by(MessageRecord.sequence))]

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
                # One batched decision for the current Run and every Run of the session (P8): each distinct
                # grant is checked once. Grants are still read on every preparation, so revocation takes effect
                # on the next Run.
                session_runs = list(db.scalars(select(RunRecord).where(RunRecord.session_id == run.session_id)))
                allowed_cache: dict[UUID, bool] = histories_allowed(db, session_runs)
                if not allowed_cache.get(run.id, False):
                    raise RuntimeFault('run_authorization_denied')
                history = []
                allowed_runs = [source.id for source in session_runs if allowed_cache[source.id]]
                source_checks: dict[UUID, bool] = {}
                # Watermark and rows are read in this transaction; grants are rechecked below on every run.
                watermark = db.scalar(select(SessionRecord.watermark).where(SessionRecord.id == run.session_id))
                rows = HISTORY_CACHE.get_or_build(run.session_id, watermark, lambda: _message_rows(db, run.session_id))
                # A usable summary replaces every row up to its cut point. Those rows are neither
                # authorized nor materialized (P8 windowing); the cut is used only if all of them are visible.
                summary = effective_summary(db, run.session_id)
                cut = 0
                if summary and summary.tenant_id == run.tenant_id and summary.source_run_id in allowed_runs:
                    covered = [row for row in rows if row['sequence'] <= summary.through_sequence]
                    if all(row['run_id'] is None or UUID(row['run_id']) in allowed_runs for row in covered):
                        cut = summary.through_sequence
                        history.append(ModelMessage('user', summary.content))
                for row in rows:
                    if row['sequence'] <= cut:
                        continue
                    if row['run_id'] is not None and UUID(row['run_id']) not in allowed_runs:
                        continue
                    metadata = row['runtime_metadata']
                    # Run-scoped replay (P10): tool exchanges of earlier Runs stay in storage for display
                    # but are not replayed to the model. This Run's exchanges are kept whole, since waits,
                    # approvals and crash recovery depend on call/result pairing.
                    is_tool_exchange = row['role'] == 'tool' or bool(metadata.get('tool_calls'))
                    if is_tool_exchange and row['run_id'] != str(run.id):
                        continue
                    if metadata.get('source_run_id'):
                        source_id = UUID(metadata['source_run_id'])
                        if source_id not in source_checks:
                            source_run = db.get(RunRecord, source_id)
                            source_checks[source_id] = bool(source_run and source_run.principal_id == run.principal_id
                                                            and _memo_allowed(db, allowed_cache, source_run))
                        if not source_checks[source_id]:
                            continue
                    history.append(ModelMessage(row['role'], row['content'],
                        tuple(ToolCall(**call) for call in metadata.get('tool_calls', [])), metadata.get('tool_call_id'), row['id']))
                checkpoint = db.get(WorkingCheckpointRecord, run.session_id)
                system = version.instructions
                from nexus_platform.memory.snapshots import session_index
                published_index = session_index(db, tenant_id=run.tenant_id, owner_id=run.principal_id,
                    session_id=run.session_id, project=version.budgets.get('behavior', {}).get('project_name', ''))
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
