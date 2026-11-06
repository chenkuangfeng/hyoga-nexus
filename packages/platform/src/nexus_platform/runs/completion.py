"""Durable execution completion; model execution stays in runtimes."""
from __future__ import annotations
from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus_core.platform import RunStatus, new_id, utc_now
from nexus_core.runtime import RuntimeOutcome
from nexus_platform.persistence.models import InputRequestRecord, RunRecord, ToolInvocationRecord
from nexus_platform.runs.service import append_event, transition_run
from nexus_platform.authz.audit import audit
from nexus_platform.memory import capture
from nexus_platform.sessions import snapshot

#: Outcomes that end a Run for good. Waiting states are resumed later and keep no terminal snapshot.
TERMINAL_OUTCOMES = frozenset({'completed', 'failed', 'cancelled', 'interrupted'})


def _finish(db: Session, run: RunRecord, outcome: RuntimeOutcome) -> None:
    transition_run(run, RunStatus(outcome.status))
    run.error_code = outcome.error_code
    run.error_message = outcome.error_code  # Stable codes only, never exception/provider text.
    run.lease_owner = None
    run.lease_until = None
    if outcome.status == 'waiting_input':
        request = InputRequestRecord(id=new_id(), run_id=run.id, question=(outcome.question or '')[:4000], candidates=list(outcome.candidates), created_at=utc_now())
        db.add(request)
        append_event(db, run.id, 'input.requested', {'input_request_id': str(request.id), 'question': request.question, 'candidates': request.candidates})
    elif outcome.status != 'waiting_approval':
        run.ended_at = utc_now()
    append_event(db, run.id, 'run.' + outcome.status, {'status': run.status, 'error_code': outcome.error_code})
    audit(db, run.tenant_id, run.principal_id, 'run.' + outcome.status, 'run', str(run.id),
          {'error_code': outcome.error_code})
    if outcome.status in TERMINAL_OUTCOMES:
        _classify_unfinished_calls(db, run)
        snapshot.record_terminal(db, run.session_id, run_id=run.id, status=outcome.status, error_code=outcome.error_code)
    if outcome.status == 'completed':
        # Citations of the final answer (openspec 2026-11-06-knowledge-base K1.8, decision 7).
        from nexus_platform.knowledge.tools import attach_citations
        attach_citations(db, run)
        # Automatic capture queues a job only for owners who opted in; off by default (stage 3).
        capture.enqueue_for_run(db, run)


def _classify_unfinished_calls(db: Session, run: RunRecord) -> None:
    """A tool call still 'running' when the Run ends did not report a result, so its effect is unknown."""
    now = utc_now()
    for invocation in db.scalars(select(ToolInvocationRecord).where(
            ToolInvocationRecord.run_id == run.id, ToolInvocationRecord.status == 'running')):
        invocation.status, invocation.error_code, invocation.ended_at = 'interrupted', 'interrupted', now
