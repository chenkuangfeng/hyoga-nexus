"""Short transaction adapters for durable Runtime execution; no model/tool loop."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import timedelta, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from nexus_core.platform import CredentialRef, Principal, RunStatus, new_id, utc_now
from nexus_core.runtime import ModelMessage, RuntimeFault, RuntimeOutcome, RuntimeProgress, ToolCall
from nexus_platform.errors import PlatformError, Conflict, NotFound
from nexus_platform.identity.service import require_membership, require_workspace, resolve_user
from nexus_platform.persistence.models import (
    AgentVersionRecord, CredentialReferenceRecord, InputRequestRecord, MessageRecord,
    ModelProfileRecord, ModelProfileVersionRecord, NativeRunStateRecord, OutboxRecord,
    ResourceBindingRecord, RunRecord, SessionRecord, ToolInvocationRecord, UserRecord,
    WorkingCheckpointRecord, MemoryDraftRecord,
)
from nexus_platform.runs.service import append_event, transition_run, authorize_run_resource
from nexus_platform.workspaces.service import audit, authorize_resource


@dataclass(frozen=True)
class ExecutionContext:
    run_id: UUID
    session_id: UUID
    workspace_id: UUID
    principal_id: UUID
    principal: Principal
    runtime_type: str
    provider: str
    model_name: str
    options: dict
    credential: CredentialRef | None
    messages: tuple[ModelMessage, ...]
    bindings: tuple[tuple[str, str, str], ...]
    budgets: dict
    progress: RuntimeProgress
    history_run_ids: tuple[UUID, ...]


def add_message(db: Session, run: RunRecord, message: ModelMessage, *, origin: str = "runtime") -> MessageRecord:
    session_row = db.scalar(select(SessionRecord).where(SessionRecord.id == run.session_id).with_for_update())
    session_row.updated_at = utc_now()
    sequence = db.scalar(select(func.coalesce(func.max(MessageRecord.sequence), 0)).where(
        MessageRecord.session_id == run.session_id)) + 1
    row = MessageRecord(id=new_id(), session_id=run.session_id, run_id=run.id, sequence=sequence,
        role=message.role, content=message.content, created_at=utc_now(),
        runtime_metadata={'origin': origin, 'tool_calls': [asdict(call) for call in message.tool_calls],
                          'tool_call_id': message.tool_call_id})
    db.add(row)
    return row


def _history_allowed(db: Session, run: RunRecord) -> bool:
    try:
        for resource in run.config_snapshot.get('resources', []):
            authorize_resource(db, run.workspace_id, resource['kind'], resource['resource_id'],
                source_workspace_id=UUID(resource['source_workspace_id']),
                resource_version_id=resource.get('resource_version_id'), permission='use')
        return True
    except PlatformError:
        return False


def _finish(db: Session, run: RunRecord, outcome: RuntimeOutcome) -> None:
    transition_run(run, RunStatus(outcome.status))
    run.error_code = outcome.error_code
    run.error_message = outcome.error_code  # Stable codes only, never exception/provider text.
    run.lease_owner = None
    run.lease_until = None
    if outcome.status == 'waiting_input':
        request = InputRequestRecord(id=new_id(), run_id=run.id, question=(outcome.question or '')[:4000], created_at=utc_now())
        db.add(request)
        append_event(db, run.id, 'input.requested', {'input_request_id': str(request.id), 'question': request.question})
    else:
        run.ended_at = utc_now()
    append_event(db, run.id, 'run.' + outcome.status, {'status': run.status, 'error_code': outcome.error_code})
    audit(db, run.workspace_id, run.principal_id, 'run.' + outcome.status, 'run', str(run.id),
          {'error_code': outcome.error_code})


def prepare_execution(factory: sessionmaker[Session], task_id: UUID, worker_id: str) -> ExecutionContext | None:
    with factory() as db, db.begin():
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
            require_workspace(db, run.workspace_id)
            require_membership(db, run.workspace_id, run.principal_id)
            if not user or user.status != 'active':
                raise RuntimeFault('run_authorization_denied')
            version = db.get(AgentVersionRecord, UUID(run.config_snapshot['agent_version_id']))
            model = db.get(ModelProfileVersionRecord, version.model_profile_version_id)
            profile = db.get(ModelProfileRecord, model.profile_id)
            credential = None
            if model.credential_reference_id:
                ref = db.get(CredentialReferenceRecord, model.credential_reference_id)
                if not ref or ref.status != 'active' or ref.workspace_id != run.workspace_id:
                    raise RuntimeFault('model_credential_unavailable')
                credential = CredentialRef(ref.id, ref.backend, ref.handle, str(run.workspace_id))
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
                history.append(ModelMessage(message.role, message.content,
                    tuple(ToolCall(**call) for call in metadata.get('tool_calls', [])), metadata.get('tool_call_id')))
            checkpoint = db.get(WorkingCheckpointRecord, run.session_id)
            system = version.instructions
            if checkpoint and checkpoint.workspace_id == run.workspace_id and checkpoint.source_run_id in allowed_runs:
                system += '\nSession working checkpoint:\n' + checkpoint.content
                audit(db, run.workspace_id, run.principal_id, 'checkpoint.read', 'session', str(run.session_id),
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
            audit(db, run.workspace_id, run.principal_id, 'session.context_read', 'session', str(run.session_id),
                  {'run_id': str(run.id), 'message_count': len(history)})
            transition_run(run, RunStatus.RUNNING)
            run.attempt += 1
            run.started_at = run.started_at or utc_now()
            run.lease_owner, run.lease_until = worker_id, task.lease_until
            append_event(db, run.id, 'run.started', {'status': 'running', 'attempt': run.attempt})
            return ExecutionContext(run.id, run.session_id, run.workspace_id, run.principal_id,
                Principal(user.subject, user.issuer), version.runtime_type, profile.provider, model.model_name,
                model.options, credential, (ModelMessage('system', system), *history), bindings,
                version.budgets, RuntimeProgress(**state.progress), tuple(allowed_runs))
        except (PlatformError, RuntimeFault) as exc:
            code = exc.code if isinstance(exc, RuntimeFault) else 'run_authorization_denied'
            _finish(db, run, RuntimeOutcome('failed', code))
            task.completed_at = utc_now()
            return None


class DurableRuntimeStore:
    def __init__(self, factory: sessionmaker[Session], context: ExecutionContext, worker_id: str, task_id: UUID):
        self.factory, self.context, self.worker_id, self.task_id = factory, context, worker_id, task_id

    def _run(self, db: Session) -> RunRecord:
        task = db.get(OutboxRecord, self.task_id)
        if (not task or task.completed_at or task.lease_owner != self.worker_id or
                not task.lease_until or task.lease_until.replace(tzinfo=timezone.utc) <= utc_now()):
            raise RuntimeFault('interrupted')
        run = db.scalar(select(RunRecord).where(RunRecord.id == self.context.run_id).with_for_update())
        if not run or run.status != 'running' or run.lease_owner != self.worker_id:
            raise RuntimeFault('interrupted')
        return run

    async def emit(self, kind: str, payload: dict[str, object]) -> None:
        with self.factory() as db, db.begin():
            run = self._run(db)
            if kind == 'model.started':
                try:
                    require_workspace(db, run.workspace_id)
                    require_membership(db, run.workspace_id, run.principal_id)
                    for source_id in self.context.history_run_ids:
                        source = db.get(RunRecord, source_id)
                        if not _history_allowed(db, source):
                            raise RuntimeFault('run_authorization_denied')
                except PlatformError:
                    raise RuntimeFault('run_authorization_denied') from None
            append_event(db, run.id, kind, payload)

    async def message(self, message: ModelMessage) -> None:
        with self.factory() as db, db.begin():
            add_message(db, self._run(db), message)

    async def save_progress(self, progress: RuntimeProgress) -> None:
        with self.factory() as db, db.begin():
            run = self._run(db)
            db.get(NativeRunStateRecord, run.id).progress = asdict(progress)

    def heartbeat(self) -> bool:
        now = utc_now()
        with self.factory() as db, db.begin():
            task = db.scalar(select(OutboxRecord).where(OutboxRecord.id == self.task_id).with_for_update())
            if not task or task.completed_at or task.lease_owner != self.worker_id:
                raise RuntimeFault('interrupted')
            run = self._run(db)
            task.lease_until = run.lease_until = now + timedelta(seconds=60)
            try:
                require_membership(db, run.workspace_id, run.principal_id)
            except PlatformError:
                return True
            return run.cancel_requested_at is not None

    def finish(self, outcome: RuntimeOutcome) -> None:
        with self.factory() as db, db.begin():
            run = self._run(db)
            _finish(db, run, outcome)
            task = db.get(OutboxRecord, self.task_id)
            task.completed_at, task.lease_owner, task.lease_until = utc_now(), None, None

    async def authorize(self, name: str, version: str) -> str:
        binding_id = next((binding for tool, ver, binding in self.context.bindings if tool == name and ver == version), None)
        if not binding_id:
            raise RuntimeFault('tool_authorization_denied')
        try:
            with self.factory() as db:
                authorize_run_resource(db, self.context.principal, self.context.workspace_id,
                                       self.context.run_id, UUID(binding_id))
        except PlatformError:
            raise RuntimeFault('tool_authorization_denied') from None
        return binding_id

    async def denied(self, name: str) -> None:
        with self.factory() as db, db.begin():
            run = self._run(db)
            audit(db, run.workspace_id, run.principal_id, 'tool.denied', 'run', str(run.id),
                  {'tool_name': name[:64]}, result='denied')

    async def start(self, call: ToolCall, binding_id: str | None) -> str:
        with self.factory() as db, db.begin():
            run = self._run(db)
            previous = db.scalar(select(ToolInvocationRecord).where(
                ToolInvocationRecord.run_id == run.id, ToolInvocationRecord.operation_id == call.id))
            if previous:
                raise RuntimeFault('interrupted')
            invocation_id = new_id()
            db.add(ToolInvocationRecord(id=invocation_id, run_id=run.id,
                resource_binding_id=UUID(binding_id) if binding_id else None,
                operation_id=call.id, status='running', input_summary={'tool_name': call.name},
                output_summary={}, started_at=utc_now()))
            append_event(db, run.id, 'tool.started', {'invocation_id': str(invocation_id), 'name': call.name})
            return str(invocation_id)

    async def finish_tool(self, invocation_id: str, status: str, summary: str, error_code: str | None) -> None:
        with self.factory() as db, db.begin():
            run = self._run(db)
            row = db.get(ToolInvocationRecord, UUID(invocation_id))
            if not row or row.run_id != run.id or row.status != 'running':
                raise RuntimeFault('interrupted')
            row.status, row.error_code, row.ended_at = status, error_code, utc_now()
            row.output_summary = {'text': summary[:4000]}
            append_event(db, run.id, 'tool.completed' if status == 'completed' else 'tool.failed',
                {'invocation_id': invocation_id, 'status': status, 'summary': summary[:4000], 'error_code': error_code})
            audit(db, run.workspace_id, run.principal_id, 'tool.' + status, 'tool_invocation', invocation_id,
                  {'run_id': str(run.id), 'error_code': error_code})

    async def checkpoint(self, content: str) -> None:
        with self.factory() as db, db.begin():
            run = self._run(db)
            row = db.get(WorkingCheckpointRecord, run.session_id)
            if not row:
                row = WorkingCheckpointRecord(session_id=run.session_id, workspace_id=run.workspace_id)
                db.add(row)
            row.source_run_id, row.content, row.updated_at = run.id, content[:8000], utc_now()
            audit(db, run.workspace_id, run.principal_id, 'checkpoint.updated', 'session', str(run.session_id),
                  {'run_id': str(run.id)})

    async def propose(self, kind: str, scope: str, diff: str) -> str:
        if kind not in ('memory', 'sop') or scope != 'session':
            raise RuntimeFault('memory_scope_invalid')
        with self.factory() as db, db.begin():
            run = self._run(db)
            row = MemoryDraftRecord(id=new_id(), workspace_id=run.workspace_id, source_run_id=run.id,
                kind=kind, scope=str(run.session_id), diff=diff[:8000], status='pending_review', created_at=utc_now())
            db.add(row)
            append_event(db, run.id, 'memory.draft_created', {'draft_id': str(row.id), 'kind': kind, 'scope': 'session'})
            audit(db, run.workspace_id, run.principal_id, 'memory.draft_created', 'memory_draft', str(row.id))
            return str(row.id)


def respond_input(db: Session, principal: Principal, workspace_id: UUID, run_id: UUID,
                  input_request_id: UUID, response: str, key: str) -> RunRecord:
    if not key.strip() or len(key) > 255:
        raise ValueError('Idempotency-Key must contain 1 to 255 characters')
    with db.begin():
        user = resolve_user(db, principal)
        require_workspace(db, workspace_id)
        require_membership(db, workspace_id, user.id)
        run = db.scalar(select(RunRecord).where(RunRecord.id == run_id,
            RunRecord.workspace_id == workspace_id, RunRecord.principal_id == user.id).with_for_update())
        if not run:
            raise NotFound('Run not found')
        request = db.get(InputRequestRecord, input_request_id)
        if not request or request.run_id != run.id:
            raise NotFound('Input request not found')
        if request.responded_at:
            if request.response_key != key or request.response != response:
                raise Conflict('Input request already consumed')
            return run
        if run.status != 'waiting_input' or run.cancel_requested_at:
            raise Conflict('Run is not waiting for input')
        request.response, request.response_key, request.responded_at = response, key, utc_now()
        add_message(db, run, ModelMessage('user', response), origin='user_input')
        append_event(db, run.id, 'input.received', {'input_request_id': str(request.id)})
        task = db.scalar(select(OutboxRecord).where(OutboxRecord.run_id == run.id,
            OutboxRecord.message_type == 'run.execute').with_for_update())
        task.completed_at, task.lease_owner, task.lease_until, task.available_at = None, None, None, utc_now()
        audit(db, workspace_id, user.id, 'input.received', 'run', str(run.id))
        return run
