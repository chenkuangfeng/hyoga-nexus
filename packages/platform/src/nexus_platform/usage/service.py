"""Token usage ledger, reports and monthly limits (openspec 2026-11-11-enterprise-saas E6).

Recording: when a Run ends the worker calls :func:`record_run_usage`, which adds the normalized ``usage`` of the
Run's ``model.completed`` events (``input``, ``output``, ``cache_read``, ``cache_creation``) to the day's row of
(enterprise, member, agent, model version). A Run is added once (``usage_recorded_runs``).

Limits: a monthly token limit may be set for the enterprise, a department (counting the members placed in it or
below it at the time of the check) or a member. Counted tokens are input plus output; cache counters are reported
but not counted. :func:`require_quota` runs at Run submission: when any applicable limit is used up the Run is
refused with 429 ``quota_exhausted``; Runs already running are not interrupted.

Reports and limits need ``models:manage``; members may read their own usage.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from nexus_core.platform import Principal, new_id, utc_now
from nexus_platform.authz.audit import audit
from nexus_platform.authz.permissions import require_api_permission
from nexus_platform.errors import InvalidConfiguration, NotFound, PlatformError
from nexus_platform.identity.service import require_membership, require_tenant, resolve_user
from nexus_platform.persistence.models import (AgentVersionRecord, OrgUnitRecord, RunEventRecord, RunRecord,
                                               SessionRecord, UsageLedgerRecord, UsageLimitRecord,
                                               UsageRecordedRunRecord, UserOrgUnitRecord)

TERMINAL = ('completed', 'failed', 'cancelled', 'interrupted')
SCOPES = ('tenant', 'org_unit', 'user')


class QuotaExhausted(PlatformError):
    code = 'quota_exhausted'
    status_code = 429


def _int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def run_usage(db: Session, run_id: UUID) -> dict[str, int]:
    totals = {'input': 0, 'output': 0, 'cache_read': 0, 'cache_creation': 0}
    for payload in db.scalars(select(RunEventRecord.payload).where(RunEventRecord.run_id == run_id,
                                                                  RunEventRecord.event_type == 'model.completed')):
        usage = (payload or {}).get('usage') or {}
        totals['input'] += _int(usage.get('input', usage.get('input_tokens', usage.get('prompt_tokens'))))
        totals['output'] += _int(usage.get('output', usage.get('output_tokens', usage.get('completion_tokens'))))
        totals['cache_read'] += _int(usage.get('cache_read'))
        totals['cache_creation'] += _int(usage.get('cache_creation'))
    return totals


def record_run_usage(db: Session, run_id: UUID) -> bool:
    """Add one ended Run to the ledger inside the caller's transaction; False when not ended or already added."""
    run = db.get(RunRecord, run_id)
    if run is None or run.status not in TERMINAL or db.get(UsageRecordedRunRecord, run_id) is not None:
        return False
    totals = run_usage(db, run_id)
    session = db.get(SessionRecord, run.session_id)
    version = db.get(AgentVersionRecord, session.agent_version_id) if session else None
    agent_id = version.agent_id if version else None
    model_id = version.model_profile_version_id if version else None
    day = (run.created_at.date() if isinstance(run.created_at, datetime) else utc_now().date())
    row = db.scalar(select(UsageLedgerRecord).where(
        UsageLedgerRecord.tenant_id == run.tenant_id, UsageLedgerRecord.day == day,
        UsageLedgerRecord.user_id == run.principal_id,
        UsageLedgerRecord.agent_id.is_(None) if agent_id is None else UsageLedgerRecord.agent_id == agent_id,
        UsageLedgerRecord.model_version_id.is_(None) if model_id is None else UsageLedgerRecord.model_version_id == model_id))
    if row is None:
        row = UsageLedgerRecord(id=new_id(), tenant_id=run.tenant_id, day=day, user_id=run.principal_id,
                                agent_id=agent_id, model_version_id=model_id, runs=0, input_tokens=0,
                                output_tokens=0, cache_read_tokens=0, cache_creation_tokens=0)
        db.add(row)
    row.runs += 1
    row.input_tokens += totals['input']
    row.output_tokens += totals['output']
    row.cache_read_tokens += totals['cache_read']
    row.cache_creation_tokens += totals['cache_creation']
    db.add(UsageRecordedRunRecord(run_id=run_id, recorded_at=utc_now()))
    db.flush()
    return True


def unrecorded_runs(db: Session, *, limit: int = 100) -> list[UUID]:
    """Ended Runs not yet in the ledger (recovers Runs whose end the worker did not see)."""
    recorded = select(UsageRecordedRunRecord.run_id)
    return list(db.scalars(select(RunRecord.id).where(RunRecord.status.in_(TERMINAL), RunRecord.id.not_in(recorded))
                           .order_by(RunRecord.created_at).limit(limit)))


# ---------------------------------------------------------------------------------------------- limits

def _month_start(today: date | None = None) -> date:
    today = today or utc_now().date()
    return today.replace(day=1)


def _counted(query):
    return query.with_only_columns(func.coalesce(func.sum(UsageLedgerRecord.input_tokens
                                                          + UsageLedgerRecord.output_tokens), 0))


def _subtree_users(db: Session, tenant_id: UUID, unit_id: UUID) -> set[UUID]:
    from nexus_platform.orgs.access import subtree_ids
    units = subtree_ids(db, unit_id)
    return set(db.scalars(select(UserOrgUnitRecord.user_id).where(UserOrgUnitRecord.tenant_id == tenant_id,
                                                                  UserOrgUnitRecord.unit_id.in_(units))))


def used_this_month(db: Session, tenant_id: UUID, scope_kind: str, scope_id: UUID) -> int:
    query = select(UsageLedgerRecord).where(UsageLedgerRecord.tenant_id == tenant_id,
                                            UsageLedgerRecord.day >= _month_start())
    if scope_kind == 'user':
        query = query.where(UsageLedgerRecord.user_id == scope_id)
    elif scope_kind == 'org_unit':
        users = _subtree_users(db, tenant_id, scope_id)
        if not users:
            return 0
        query = query.where(UsageLedgerRecord.user_id.in_(users))
    return int(db.scalar(_counted(query)) or 0)


def require_quota(db: Session, tenant_id: UUID, user_id: UUID) -> None:
    """Refuse a new Run while a limit that applies to the member is used up this month."""
    limits = db.scalars(select(UsageLimitRecord).where(UsageLimitRecord.tenant_id == tenant_id)).all()
    if not limits:
        return
    from nexus_platform.authz.audiences import placement
    units = placement(db, tenant_id, user_id).with_ancestors
    for limit in limits:
        applies = ((limit.scope_kind == 'tenant') or (limit.scope_kind == 'user' and limit.scope_id == user_id)
                   or (limit.scope_kind == 'org_unit' and limit.scope_id in units))
        if applies and used_this_month(db, tenant_id, limit.scope_kind, limit.scope_id) >= limit.monthly_tokens:
            raise QuotaExhausted(f'本月的 {limit.scope_kind} 用量已达上限，请联系企业管理员')


def _manager(db: Session, principal: Principal, tenant_id: UUID):
    user = resolve_user(db, principal)
    require_tenant(db, tenant_id)
    require_membership(db, tenant_id, user.id)
    require_api_permission(db, tenant_id, user.id, 'models:manage')
    return user


def limit_view(db: Session, row: UsageLimitRecord) -> dict[str, Any]:
    return {'id': str(row.id), 'scope_kind': row.scope_kind, 'scope_id': str(row.scope_id),
            'monthly_tokens': row.monthly_tokens,
            'used_this_month': used_this_month(db, row.tenant_id, row.scope_kind, row.scope_id)}


def list_limits(db: Session, principal: Principal, tenant_id: UUID) -> list[dict[str, Any]]:
    with db.begin():
        _manager(db, principal, tenant_id)
        rows = db.scalars(select(UsageLimitRecord).where(UsageLimitRecord.tenant_id == tenant_id)).all()
        return [limit_view(db, row) for row in rows]


def set_limit(db: Session, principal: Principal, tenant_id: UUID, *, scope_kind: str, scope_id: UUID | None,
              monthly_tokens: int | None) -> dict[str, Any] | None:
    """Create, change or (``monthly_tokens`` None) remove the limit of one scope."""
    if scope_kind not in SCOPES:
        raise InvalidConfiguration('scope_kind must be tenant, org_unit or user')
    with db.begin():
        user = _manager(db, principal, tenant_id)
        scope_id = tenant_id if scope_kind == 'tenant' else scope_id
        if scope_id is None:
            raise InvalidConfiguration('scope_id is required')
        if scope_kind == 'org_unit':
            unit = db.get(OrgUnitRecord, scope_id)
            if unit is None or unit.tenant_id != tenant_id:
                raise NotFound('Department not found')
        if scope_kind == 'user':
            require_membership(db, tenant_id, scope_id)
        row = db.scalar(select(UsageLimitRecord).where(UsageLimitRecord.tenant_id == tenant_id,
                                                       UsageLimitRecord.scope_kind == scope_kind,
                                                       UsageLimitRecord.scope_id == scope_id))
        if monthly_tokens is None:
            if row is not None:
                db.delete(row)
            audit(db, tenant_id, user.id, 'usage.limit_removed', scope_kind, str(scope_id), {})
            return None
        if monthly_tokens <= 0:
            raise InvalidConfiguration('monthly_tokens must be positive')
        if row is None:
            row = UsageLimitRecord(id=new_id(), tenant_id=tenant_id, scope_kind=scope_kind, scope_id=scope_id,
                                   monthly_tokens=monthly_tokens, updated_by=user.id, updated_at=utc_now())
            db.add(row)
        else:
            row.monthly_tokens, row.updated_by, row.updated_at = monthly_tokens, user.id, utc_now()
        db.flush()
        audit(db, tenant_id, user.id, 'usage.limit_set', scope_kind, str(scope_id), {'monthly_tokens': monthly_tokens})
        return limit_view(db, row)


# ---------------------------------------------------------------------------------------------- reports

GROUPS = {'user': UsageLedgerRecord.user_id, 'agent': UsageLedgerRecord.agent_id,
          'model': UsageLedgerRecord.model_version_id, 'day': UsageLedgerRecord.day}


def report(db: Session, principal: Principal, tenant_id: UUID, *, group_by: str, start: date | None = None,
           end: date | None = None, only_self: bool = False) -> list[dict[str, Any]]:
    """Sums grouped by ``user``, ``agent``, ``model``, ``day`` or ``org_unit`` (members' primary departments)."""
    if group_by not in (*GROUPS, 'org_unit'):
        raise InvalidConfiguration('group_by must be user, agent, model, day or org_unit')
    with db.begin():
        user = resolve_user(db, principal)
        require_tenant(db, tenant_id)
        require_membership(db, tenant_id, user.id)
        if not only_self:
            require_api_permission(db, tenant_id, user.id, 'models:manage')
        start = start or _month_start()
        end = end or utc_now().date()
        sums = (func.sum(UsageLedgerRecord.runs), func.sum(UsageLedgerRecord.input_tokens),
                func.sum(UsageLedgerRecord.output_tokens), func.sum(UsageLedgerRecord.cache_read_tokens),
                func.sum(UsageLedgerRecord.cache_creation_tokens))
        key = UsageLedgerRecord.user_id if group_by == 'org_unit' else GROUPS[group_by]
        query = select(key, *sums).where(UsageLedgerRecord.tenant_id == tenant_id, UsageLedgerRecord.day >= start,
                                         UsageLedgerRecord.day <= end).group_by(key)
        if only_self:
            query = query.where(UsageLedgerRecord.user_id == user.id)
        rows = db.execute(query).all()
        result: dict[str, dict[str, int]] = {}
        for value, runs, inp, out, cread, ccreate in rows:
            if group_by == 'org_unit':
                value = db.scalar(select(UserOrgUnitRecord.unit_id).where(
                    UserOrgUnitRecord.tenant_id == tenant_id, UserOrgUnitRecord.user_id == value,
                    UserOrgUnitRecord.is_primary.is_(True)))
            bucket = result.setdefault(str(value) if value is not None else '', {
                'runs': 0, 'input_tokens': 0, 'output_tokens': 0, 'cache_read_tokens': 0, 'cache_creation_tokens': 0})
            for name, amount in zip(bucket, (runs, inp, out, cread, ccreate)):
                bucket[name] += int(amount or 0)
        return [{'key': key_value, **values} for key_value, values in sorted(result.items())]


__all__ = ['QuotaExhausted', 'list_limits', 'record_run_usage', 'report', 'require_quota', 'set_limit',
           'unrecorded_runs', 'used_this_month']
