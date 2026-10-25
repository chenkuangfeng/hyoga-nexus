"""WeKnora action approvals translated independently of Workspace ResourceGrant.

A request is tied to the exact Run configuration and tool call. Approving does not execute
anything: the resumed worker must reauthorize the tool and consume the decision once.
"""
import hashlib
import json
from sqlalchemy import select
from nexus_core.platform import new_id, utc_now
from nexus_core.runtime import ToolResult, ToolDisposition
from nexus_platform.persistence.models import ActionApprovalRecord, RunRecord, OutboxRecord, NativeRunStateRecord
from nexus_platform.models.provider_settings import context
from nexus_platform.models.service import clean_public_options
from nexus_platform.errors import NotFound, Conflict
from nexus_platform.runs.service import append_event
from nexus_platform.workspaces.service import audit


def binding_hash(run) -> str:
    return hashlib.sha256(json.dumps(run.config_snapshot, sort_keys=True).encode()).hexdigest()


def request(db, run, call):
    """Return an existing unconsumed decision or persist a new pending action prompt."""
    row = db.scalar(select(ActionApprovalRecord).where(ActionApprovalRecord.run_id == run.id,
        ActionApprovalRecord.tool_call_id == call.id).with_for_update())
    if row:
        if row.binding_hash != binding_hash(run) or row.tool_name != call.name:
            raise Conflict('Approval configuration changed')
        if row.status == 'approved':
            row.status, row.consumed_at = 'consumed', utc_now()
            audit(db, run.workspace_id, run.principal_id, 'approval.consumed', 'approval', str(row.id))
            return row.modified_arguments or row.arguments
        if row.status == 'rejected':
            row.status, row.consumed_at = 'consumed', utc_now()
            return ToolResult('Action rejected by user', error_code='tool_approval_rejected')
        if row.status == 'consumed':
            raise Conflict('Approval already consumed; do not replay')
    else:
        arguments = json.loads(call.arguments)
        clean_public_options(arguments, 'approval')
        row = ActionApprovalRecord(id=new_id(), run_id=run.id, tool_call_id=call.id, tool_name=call.name,
            arguments=call.arguments, binding_hash=binding_hash(run), status='pending', created_at=utc_now())
        db.add(row)
        append_event(db, run.id, 'approval.requested', {'approval_id': str(row.id), 'tool_name': call.name})
    return ToolResult('Approval required for ' + call.name, disposition=ToolDisposition.WAIT_APPROVAL)


def list_pending(db, principal, workspace_id, run_id):
    """Expose action arguments only to the Run owner, never through generic tool events."""
    with db.begin():
        user, _ = context(db, principal, workspace_id)
        run = db.get(RunRecord, run_id)
        if not run or run.workspace_id != workspace_id or run.principal_id != user.id:
            raise NotFound('Run unavailable')
        return [{'id': str(row.id), 'tool_name': row.tool_name, 'arguments': json.loads(row.arguments)} for row in db.scalars(
            select(ActionApprovalRecord).where(ActionApprovalRecord.run_id == run_id, ActionApprovalRecord.status == 'pending'))]


def resolve(db, principal, workspace_id, run_id, approval_id, approve, arguments=None):
    """Resolve once, persist the decision, and requeue the original blocked Run."""
    with db.begin():
        user, _ = context(db, principal, workspace_id)
        run = db.scalar(select(RunRecord).where(RunRecord.id == run_id, RunRecord.workspace_id == workspace_id,
            RunRecord.principal_id == user.id).with_for_update())
        row = db.get(ActionApprovalRecord, approval_id)
        if not run or not row or row.run_id != run.id:
            raise NotFound('Approval unavailable')
        if row.status != 'pending' or run.status != 'waiting_approval' or run.cancel_requested_at:
            raise Conflict('Approval is not pending')
        if arguments is not None:
            clean_public_options(arguments, 'approval')
            row.modified_arguments = json.dumps(arguments, ensure_ascii=False)
        row.status, row.resolved_at = 'approved' if approve else 'rejected', utc_now()
        # Returning to queued is explicit; existing completed invocations remain immutable.
        run.status = 'queued'
        task = db.scalar(select(OutboxRecord).where(OutboxRecord.run_id == run.id, OutboxRecord.message_type == 'run.execute').with_for_update())
        task.completed_at, task.lease_owner, task.lease_until, task.available_at = None, None, None, utc_now()
        append_event(db, run.id, 'approval.resolved', {'approval_id': str(row.id), 'approved': approve})
        audit(db, workspace_id, user.id, 'approval.resolved', 'approval', str(row.id), {'approved': approve})
        return {'status': row.status}
