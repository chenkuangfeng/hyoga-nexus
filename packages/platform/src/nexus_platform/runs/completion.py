"""Durable execution completion; model execution stays in runtimes."""
from __future__ import annotations
from sqlalchemy.orm import Session
from nexus_core.platform import RunStatus, new_id, utc_now
from nexus_core.runtime import RuntimeOutcome
from nexus_platform.persistence.models import InputRequestRecord, RunRecord
from nexus_platform.runs.service import append_event, transition_run
from nexus_platform.authz.audit import audit


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
    audit(db, run.workspace_id, run.principal_id, 'run.' + outcome.status, 'run', str(run.id),
          {'error_code': outcome.error_code})
