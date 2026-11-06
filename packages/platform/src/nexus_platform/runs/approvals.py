"""WeKnora action approvals translated independently of Tenant ResourceGrant.

A request is tied to the exact Run configuration and tool call. Approving does not execute
anything: the resumed worker must reauthorize the tool and consume the decision once.

Session grants (openspec 2026-11-06-tool-call-hardening E; WeKnora `approval/grants.go`, Octop
`hitl_session.py`): approving with `remember='session'` also records an ActionGrant for (session, agent
version, tool). Later calls asked for by policy are let through by `grant_for_call`, which is checked on
every call, so revoking takes effect at once. Destructive tools and guard-triggered approvals are never
remembered.
"""
import hashlib
import json
from sqlalchemy import select
from nexus_core.platform import new_id, utc_now
from nexus_core.runtime import ToolResult, ToolDisposition
from uuid import UUID
from nexus_platform.persistence.models import (ActionApprovalRecord, ActionGrantRecord, NativeRunStateRecord,
                                               OutboxRecord, RunRecord, SessionRecord)
from nexus_platform.models.provider_settings import context
from nexus_platform.models.service import clean_public_options
from nexus_platform.errors import NotFound, Conflict
from nexus_platform.runs.service import append_event
from nexus_platform.authz.audit import audit


def binding_hash(run) -> str:
    return hashlib.sha256(json.dumps(run.config_snapshot, sort_keys=True).encode()).hexdigest()


def request(db, run, call, *, reason: str = 'policy', risk: str | None = None, rules=()):
    """Return an existing unconsumed decision or persist a new pending action prompt.

    `reason` (`policy` / `guard`) and `risk` are kept on the prompt: they decide whether the owner may
    remember the approval for the session.
    """
    row = db.scalar(select(ActionApprovalRecord).where(ActionApprovalRecord.run_id == run.id,
        ActionApprovalRecord.tool_call_id == call.id).with_for_update())
    if row:
        if row.binding_hash != binding_hash(run) or row.tool_name != call.name:
            raise Conflict('Approval configuration changed')
        if row.status == 'approved':
            row.status, row.consumed_at = 'consumed', utc_now()
            audit(db, run.tenant_id, run.principal_id, 'approval.consumed', 'approval', str(row.id))
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
            arguments=call.arguments, binding_hash=binding_hash(run), status='pending', created_at=utc_now(),
            reason=reason, risk=risk)
        db.add(row)
        payload = {'approval_id': str(row.id), 'tool_name': call.name, 'reason': reason,
                   'rememberable': rememberable(row)}
        if rules:
            payload['guard_rules'] = [dict(rule) for rule in rules][:5]  # shown on the approval card
        append_event(db, run.id, 'approval.requested', payload)
    return ToolResult('Approval required for ' + call.name, disposition=ToolDisposition.WAIT_APPROVAL)


def rememberable(row: ActionApprovalRecord) -> bool:
    """Whether "allow for this session" may be offered for this prompt."""
    return row.reason == 'policy' and row.risk != 'destructive'


def _agent_version(run) -> UUID | None:
    value = (run.config_snapshot or {}).get('agent_version_id')
    return UUID(str(value)) if value else None


def grant_for_call(db, run, call) -> bool:
    """True when an active session grant covers this call; records `approval.grant_used`."""
    version = _agent_version(run)
    if version is None:
        return False
    row = db.scalar(select(ActionGrantRecord).where(
        ActionGrantRecord.scope == 'session', ActionGrantRecord.scope_id == run.session_id,
        ActionGrantRecord.agent_version_id == version, ActionGrantRecord.tool_name == call.name,
        ActionGrantRecord.revoked_at.is_(None)))
    if row is None or row.risk == 'destructive':
        return False
    audit(db, run.tenant_id, run.principal_id, 'approval.grant_used', 'action_grant', str(row.id),
          {'run_id': str(run.id), 'tool_name': call.name})
    return True


def _owned_session(db, principal, tenant_id, session_id):
    user, _ = context(db, principal, tenant_id)
    session = db.get(SessionRecord, session_id)
    if session is None or session.tenant_id != tenant_id or session.owner_user_id != user.id:
        raise NotFound('Session unavailable')
    return user, session


def list_grants(db, principal, tenant_id, session_id):
    """Active session grants of the caller's own session (others get 404)."""
    with db.begin():
        _, session = _owned_session(db, principal, tenant_id, session_id)
        rows = db.scalars(select(ActionGrantRecord).where(
            ActionGrantRecord.scope == 'session', ActionGrantRecord.scope_id == session.id,
            ActionGrantRecord.revoked_at.is_(None)).order_by(ActionGrantRecord.created_at))
        return [{'id': str(row.id), 'tool_name': row.tool_name, 'risk': row.risk,
                 'agent_version_id': str(row.agent_version_id), 'created_at': row.created_at.isoformat()} for row in rows]


def revoke_grant(db, principal, tenant_id, session_id, grant_id):
    """Revoke one grant of the caller's own session; the next call asks again."""
    with db.begin():
        user, session = _owned_session(db, principal, tenant_id, session_id)
        row = db.get(ActionGrantRecord, grant_id)
        if row is None or row.scope != 'session' or row.scope_id != session.id or row.revoked_at is not None:
            raise NotFound('Grant unavailable')
        row.revoked_at = utc_now()
        audit(db, tenant_id, user.id, 'approval.grant_revoked', 'action_grant', str(row.id), {'tool_name': row.tool_name})
        return {'status': 'revoked'}


def list_pending(db, principal, tenant_id, run_id):
    """Expose action arguments only to the Run owner, never through generic tool events."""
    with db.begin():
        user, _ = context(db, principal, tenant_id)
        run = db.get(RunRecord, run_id)
        if not run or run.tenant_id != tenant_id or run.principal_id != user.id:
            raise NotFound('Run unavailable')
        return [{'id': str(row.id), 'tool_name': row.tool_name, 'arguments': json.loads(row.arguments),
                 'reason': row.reason, 'rememberable': rememberable(row)} for row in db.scalars(
            select(ActionApprovalRecord).where(ActionApprovalRecord.run_id == run_id, ActionApprovalRecord.status == 'pending'))]


def resolve(db, principal, tenant_id, run_id, approval_id, approve, arguments=None, remember: str = 'once'):
    """Resolve once, persist the decision, and requeue the original blocked Run.

    `remember='session'` with an approval also grants the tool for the rest of the session under this agent
    version; it is refused (ValueError, 422) for destructive tools and guard-triggered prompts.
    """
    if remember not in ('once', 'session'):
        raise ValueError('remember must be once or session')
    with db.begin():
        user, _ = context(db, principal, tenant_id)
        run = db.scalar(select(RunRecord).where(RunRecord.id == run_id, RunRecord.tenant_id == tenant_id,
            RunRecord.principal_id == user.id).with_for_update())
        row = db.get(ActionApprovalRecord, approval_id)
        if not run or not row or row.run_id != run.id:
            raise NotFound('Approval unavailable')
        if row.status != 'pending' or run.status != 'waiting_approval' or run.cancel_requested_at:
            raise Conflict('Approval is not pending')
        if approve and remember == 'session':
            if not rememberable(row):
                raise ValueError('This approval cannot be remembered for the session')
            version = _agent_version(run)
            existing = db.scalar(select(ActionGrantRecord).where(
                ActionGrantRecord.scope == 'session', ActionGrantRecord.scope_id == run.session_id,
                ActionGrantRecord.agent_version_id == version, ActionGrantRecord.tool_name == row.tool_name,
                ActionGrantRecord.revoked_at.is_(None)))
            if version is not None and existing is None:
                grant = ActionGrantRecord(id=new_id(), tenant_id=tenant_id, principal_id=user.id, scope='session',
                                          scope_id=run.session_id, agent_version_id=version, tool_name=row.tool_name,
                                          risk=row.risk or 'write', created_at=utc_now())
                db.add(grant)
                audit(db, tenant_id, user.id, 'approval.grant_created', 'action_grant', str(grant.id),
                      {'tool_name': row.tool_name, 'session_id': str(run.session_id)})
        if arguments is not None:
            clean_public_options(arguments, 'approval')
            row.modified_arguments = json.dumps(arguments, ensure_ascii=False)
        row.status, row.resolved_at = 'approved' if approve else 'rejected', utc_now()
        # Returning to queued is explicit; existing completed invocations remain immutable.
        run.status = 'queued'
        task = db.scalar(select(OutboxRecord).where(OutboxRecord.run_id == run.id, OutboxRecord.message_type == 'run.execute').with_for_update())
        task.completed_at, task.lease_owner, task.lease_until, task.available_at = None, None, None, utc_now()
        append_event(db, run.id, 'approval.resolved', {'approval_id': str(row.id), 'approved': approve})
        audit(db, tenant_id, user.id, 'approval.resolved', 'approval', str(row.id), {'approved': approve})
        return {'status': row.status}
