"""Durable execution store; model execution stays in runtimes."""
from __future__ import annotations
from nexus_platform.persistence.unit_of_work import SqlAlchemyUnitOfWork
from dataclasses import asdict
from datetime import timedelta, timezone
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker
from nexus_core.platform import new_id, utc_now
from nexus_core.native.policy import NativePolicy, TOOL_OUTPUT_STORE_LIMIT
from nexus_core.runtime import ModelMessage, RuntimeFault, RuntimeOutcome, RuntimeProgress, ToolCall
from nexus_platform.errors import PlatformError
from nexus_platform.models.provider_settings import authorize_model
from nexus_platform.identity.service import require_membership, require_tenant
from nexus_platform.persistence.models import (
    MessageRecord,
    NativeRunStateRecord,
    OutboxRecord,
    RunRecord,
    ToolInvocationRecord,
    WorkingCheckpointRecord,
    MemoryDraftRecord,
    ContextSummaryRecord,
    ToolOutputRecord,
)
from nexus_platform.persistence.models.event import RunEventRecord
from nexus_platform.runs.service import append_event, authorize_run_resource
from .watchdog import ALERT_EVENT, TOOL_STARTED_EVENT, Observation, WatchdogSettings, evaluate, tool_signature
from nexus_platform.authz.audit import audit
from .context import ExecutionContext
from .summaries import append_summary
from .messages import add_message
from .messages import histories_allowed
from .completion import _finish


def _behavior(context: ExecutionContext) -> NativePolicy:
    """The Run's Native behavior settings, or the defaults if they are invalid.

    Invalid settings are rejected by the worker before execution; this fallback only keeps the store
    constructible for read paths that never run a model.
    """
    try:
        return NativePolicy(**(context.budgets.get('behavior') or {}))
    except (ValueError, TypeError):
        return NativePolicy()


class DurableRuntimeStore:
    def __init__(self, factory: sessionmaker[Session], context: ExecutionContext, worker_id: str, task_id: UUID):
        self.factory, self.context, self.worker_id, self.task_id = factory, context, worker_id, task_id
        behavior = _behavior(context)
        self.page_chars, self.summary_chars = behavior.tool_output_page_chars, behavior.summary_max_chars

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
        with SqlAlchemyUnitOfWork(self.factory) as work:
            db = work.session
            run = self._run(db)
            if kind == 'model.started':
                try:
                    authorize_model(db, run.tenant_id, run.principal_id,
                                    UUID(run.config_snapshot['model_profile_version_id']))
                    require_tenant(db, run.tenant_id)
                    require_membership(db, run.tenant_id, run.principal_id)
                    # One batched decision for all history sources (P8), not one check per source Run.
                    sources = [db.get(RunRecord, source_id) for source_id in self.context.history_run_ids]
                    if any(source is None for source in sources) or not all(histories_allowed(db, sources).values()):
                        raise RuntimeFault('run_authorization_denied')
                except PlatformError:
                    raise RuntimeFault('run_authorization_denied') from None
            append_event(db, run.id, kind, payload)

    async def message(self, message: ModelMessage) -> None:
        with SqlAlchemyUnitOfWork(self.factory) as work:
            db = work.session
            row = add_message(db, self._run(db), message)
            return str(row.id)

    async def commit(self, events=(), message: ModelMessage | None = None,
                     progress: RuntimeProgress | None = None) -> str | None:
        """Write adjacent observations in one transaction under one lease check (P7).

        Equivalent to the separate `emit`, `message` and `save_progress` calls in order, but the
        lease and Run lock are checked once and a failure rolls the whole group back. Returns the
        stored message identifier, or None when no message was written.
        """
        with SqlAlchemyUnitOfWork(self.factory) as work:
            db = work.session
            run = self._run(db)
            for kind, payload in events:
                append_event(db, run.id, kind, payload)
            identifier = None
            if message is not None:
                identifier = str(add_message(db, run, message).id)
            if progress is not None:
                db.get(NativeRunStateRecord, run.id).progress = asdict(progress)
            return identifier

    async def save_progress(self, progress: RuntimeProgress) -> None:
        with SqlAlchemyUnitOfWork(self.factory) as work:
            db = work.session
            run = self._run(db)
            db.get(NativeRunStateRecord, run.id).progress = asdict(progress)

    def heartbeat(self) -> bool:
        now = utc_now()
        with SqlAlchemyUnitOfWork(self.factory) as work:
            db = work.session
            task = db.scalar(select(OutboxRecord).where(OutboxRecord.id == self.task_id).with_for_update())
            if not task or task.completed_at or task.lease_owner != self.worker_id:
                raise RuntimeFault('interrupted')
            run = self._run(db)
            task.lease_until = run.lease_until = now + timedelta(seconds=60)
            try:
                require_membership(db, run.tenant_id, run.principal_id)
            except PlatformError:
                return True
            return run.cancel_requested_at is not None

    def watch(self, settings: WatchdogSettings, alerted: set[str]) -> None:
        """Report stalls as ``run.watchdog_alert`` events. The watchdog never changes the Run.

        ``alerted`` is the caller's record of rules already reported in the current episode. A rule
        that stops holding is forgotten, so a Run that recovers and stalls again is reported again.
        Alerts are recorded only after the transaction commits, so a rolled-back write is retried.
        A lost lease or a Run that is no longer running is not an error here: the heartbeat handles it.
        """
        fired: list[str] = []
        with SqlAlchemyUnitOfWork(self.factory) as work:
            db = work.session
            try:
                run = self._run(db)
            except RuntimeFault:
                alerted.clear()
                return
            last = db.scalar(select(RunEventRecord.occurred_at).where(RunEventRecord.run_id == run.id)
                             .order_by(RunEventRecord.sequence.desc()).limit(1))
            recent = db.execute(select(RunEventRecord.id, RunEventRecord.payload).where(
                RunEventRecord.run_id == run.id, RunEventRecord.event_type == TOOL_STARTED_EVENT)
                .order_by(RunEventRecord.sequence.desc()).limit(settings.repeat_threshold)).all()
            # Events written before signatures existed get a unique value, so they never count as repeats.
            signatures = [payload.get('signature') or f'unsigned:{event_id}' for event_id, payload in reversed(recent)]
            alerts = evaluate(Observation(status=run.status, now=utc_now(), last_event_at=last,
                                          tool_signatures=signatures), settings)
            for alert in alerts:
                if alert.rule not in alerted:
                    append_event(db, run.id, ALERT_EVENT, alert.payload())
                    fired.append(alert.rule)
        alerted.intersection_update({alert.rule for alert in alerts})
        alerted.update(fired)

    def finish(self, outcome: RuntimeOutcome) -> None:
        with SqlAlchemyUnitOfWork(self.factory) as work:
            db = work.session
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
                authorize_run_resource(db, self.context.principal, self.context.tenant_id,
                                       self.context.run_id, UUID(binding_id))
        except PlatformError:
            raise RuntimeFault('tool_authorization_denied') from None
        return binding_id

    async def denied(self, name: str) -> None:
        with SqlAlchemyUnitOfWork(self.factory) as work:
            db = work.session
            run = self._run(db)
            audit(db, run.tenant_id, run.principal_id, 'tool.denied', 'run', str(run.id),
                  {'tool_name': name[:64]}, result='denied')

    async def start(self, call: ToolCall, binding_id: str | None) -> str:
        with SqlAlchemyUnitOfWork(self.factory) as work:
            db = work.session
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
            append_event(db, run.id, 'tool.started', {'invocation_id': str(invocation_id), 'name': call.name,
                'signature': tool_signature(call.name, call.arguments)})
            return str(invocation_id)

    async def approval(self, call: ToolCall):
        """Persist/consume a per-call action decision after current resource authorization."""
        from .approvals import request
        with SqlAlchemyUnitOfWork(self.factory) as work:
            db = work.session
            return request(db, self._run(db), call)

    async def tool_progress(self, invocation_id: str, text: str) -> None:
        """Persist only the registered tool's public projection of intermediate output."""
        await self.emit('tool.progress', {'invocation_id': invocation_id, 'text': text[:4000]})

    async def finish_tool(self, invocation_id: str, status: str, summary: str, error_code: str | None) -> None:
        with SqlAlchemyUnitOfWork(self.factory) as work:
            db = work.session
            run = self._run(db)
            row = db.get(ToolInvocationRecord, UUID(invocation_id))
            if not row or row.run_id != run.id or row.status != 'running':
                raise RuntimeFault('interrupted')
            row.status, row.error_code, row.ended_at = status, error_code, utc_now()
            row.output_summary = {'text': summary[:4000]}
            append_event(db, run.id, 'tool.completed' if status == 'completed' else 'tool.failed',
                {'invocation_id': invocation_id, 'status': status, 'summary': summary[:4000], 'error_code': error_code})
            audit(db, run.tenant_id, run.principal_id, 'tool.' + status, 'tool_invocation', invocation_id,
                  {'run_id': str(run.id), 'error_code': error_code})

    async def spill_tool_output(self, invocation_id: str, content: str) -> str:
        """Store the full text of one running invocation's result and return its handle (P2).

        Only the current Run's running invocation may own an output, so a handle cannot be attached
        to another Run's call. Content beyond TOOL_OUTPUT_STORE_LIMIT is not kept.
        """
        with SqlAlchemyUnitOfWork(self.factory) as work:
            db = work.session
            run = self._run(db)
            invocation = db.get(ToolInvocationRecord, UUID(invocation_id))
            if not invocation or invocation.run_id != run.id or invocation.status != 'running':
                raise RuntimeFault('interrupted')
            require_membership(db, run.tenant_id, run.principal_id)
            stored = content[:TOOL_OUTPUT_STORE_LIMIT]
            row = ToolOutputRecord(id=new_id(), run_id=run.id, tenant_id=run.tenant_id, invocation_id=invocation.id,
                                   content=stored, size_chars=len(content), created_at=utc_now())
            db.add(row)
            return str(row.id)

    async def read_tool_output(self, handle: str, offset: int) -> tuple[str, int, int | None] | None:
        """Return one page of an output of this Run: (text, total_chars, next_offset or None).

        Returns None for unknown handles, handles of other Runs, and malformed handles. The caller
        turns None into a tool error, so a bad handle never fails the Run.
        """
        try:
            identifier = UUID(handle)
        except (ValueError, TypeError):
            return None
        with SqlAlchemyUnitOfWork(self.factory) as work:
            db = work.session
            run = self._run(db)
            require_membership(db, run.tenant_id, run.principal_id)
            row = db.scalar(select(ToolOutputRecord).where(
                ToolOutputRecord.id == identifier, ToolOutputRecord.run_id == run.id))
            if row is None:
                return None
            end = min(offset + self.page_chars, len(row.content))
            audit(db, run.tenant_id, run.principal_id, 'tool_output.read', 'tool_output', handle,
                  {'run_id': str(run.id), 'offset': offset, 'end': end})
            # Total is the original size, which may exceed the stored text when the store limit applied.
            return row.content[offset:end], row.size_chars, end if end < len(row.content) else None

    async def save_summary(self, summary: str, source_id: str) -> None:
        """Persist only a cutpoint belonging to this Session; later reads recheck source grants."""
        with SqlAlchemyUnitOfWork(self.factory) as work:
            db = work.session
            run = self._run(db)
            source = db.get(MessageRecord, UUID(source_id))
            if not source or source.session_id != run.session_id:
                raise RuntimeFault('context_source_invalid')
            # Append-only (P11): a new row supersedes the effective one; existing rows are never rewritten.
            append_summary(db, session_id=run.session_id, tenant_id=run.tenant_id, source_run_id=run.id,
                           through_sequence=source.sequence, content=summary, max_chars=self.summary_chars)
            audit(db, run.tenant_id, run.principal_id, 'context.summary_saved', 'session', str(run.session_id))

    async def drain_steer(self) -> list[ModelMessage]:
        """Consume corrections under the same lease/Run lock as message persistence."""
        from .directives import consume
        with SqlAlchemyUnitOfWork(self.factory) as work:
            db = work.session
            run = self._run(db)
            require_tenant(db, run.tenant_id)
            require_membership(db, run.tenant_id, run.principal_id)
            return consume(db, run, add_message)

    async def memory_index(self) -> str:
        """Read the published pointer index for this principal without exposing drafts."""
        from nexus_platform.memory.service import index
        with SqlAlchemyUnitOfWork(self.factory) as work:
            db = work.session
            run = self._run(db)
            require_membership(db, run.tenant_id, run.principal_id)
            result = index(db, run.tenant_id, run.principal_id)
            audit(db, run.tenant_id, run.principal_id, 'memory.index_read', 'run', str(run.id))
            return result

    async def read_memory(self, entry_id: str) -> str:
        """Authorize each model memory read at execution time, independently of old indexes."""
        from nexus_platform.memory.service import read_for_run
        with SqlAlchemyUnitOfWork(self.factory) as work:
            db = work.session
            run = self._run(db)
            require_membership(db, run.tenant_id, run.principal_id)
            return read_for_run(db, run.tenant_id, run.principal_id, UUID(entry_id), run.id)

    async def checkpoint(self, content: str) -> None:
        with SqlAlchemyUnitOfWork(self.factory) as work:
            db = work.session
            run = self._run(db)
            row = db.get(WorkingCheckpointRecord, run.session_id)
            if not row:
                row = WorkingCheckpointRecord(session_id=run.session_id, tenant_id=run.tenant_id)
                db.add(row)
            row.source_run_id, row.content, row.updated_at = run.id, content[:8000], utc_now()
            audit(db, run.tenant_id, run.principal_id, 'checkpoint.updated', 'session', str(run.session_id),
                  {'run_id': str(run.id)})

    async def propose(self, kind: str, scope: str, diff: str, *, entry_id: str | None = None,
                      base_version: int | None = None) -> str:
        """Screen and record a draft for review; returns a short outcome line the model can read.

        Refusals (threat rules, tombstones, duplicates, budget, stale base) do not fail the Run:
        they are reported as text so the model can adjust. Only an invalid kind or scope fails.
        """
        from nexus_platform.memory.service import propose as propose_draft
        from nexus_platform.errors import Conflict, NotFound
        if kind not in ('memory', 'sop') or scope != 'session':
            raise RuntimeFault('memory_scope_invalid')
        with SqlAlchemyUnitOfWork(self.factory) as work:
            db = work.session
            run = self._run(db)
            try:
                outcome = propose_draft(db, run.tenant_id, run.principal_id, run.id, kind, diff,
                                        entry_id=UUID(entry_id) if entry_id else None, base_version=base_version)
            except (Conflict, NotFound) as exc:
                return f'Draft not created: {exc}'
            status = outcome['status']
            if status == 'pending':
                append_event(db, run.id, 'memory.draft_created', {'draft_id': outcome['id'], 'kind': kind, 'scope': 'session'})
                return 'Draft pending review: ' + outcome['id']
            if status == 'duplicate':
                return f"Not created: the same content already exists as {outcome['target']} {outcome['id']}."
            if status == 'budget_exceeded':
                titles = '; '.join(f"{e['title']} ({e['id']}, {e['chars']} chars)" for e in outcome['entries'])
                return (f"Not created: memory budget {outcome['budget']} chars would be exceeded. "
                        f"Merge or propose removal of existing entries first: {titles}")
            if outcome.get('reason') == 'threat':
                return 'Not created: the content matched prohibited instruction patterns: ' + ', '.join(outcome['rules'])
            return 'Not created: the owner previously rejected this content.'

    async def search_memory(self, query: str, limit: int) -> str:
        """Keyword search over the principal's live published memory; pointers and snippets only."""
        from nexus_platform.memory.service import search as search_entries
        with SqlAlchemyUnitOfWork(self.factory) as work:
            db = work.session
            run = self._run(db)
            require_membership(db, run.tenant_id, run.principal_id)
            hits = search_entries(db, run.tenant_id, run.principal_id, query, limit)
            if not hits:
                return 'No matching published memory.'
            return '\n'.join(f"[{h['id']}] {h['kind']} | {h['title']} | v{h['version']} | {h['snippet']}" for h in hits)
