"""Automatic memory capture: settings, job queue and the step-by-step job state machine (stage 3).

Lifecycle of one job (`memory_capture_jobs.state`):
    pending --extract--> extracted --store--> stored --finish--> completed
    any step that raises --> back to its own state with backoff, or `failed` after MAX_ATTEMPTS

Each step commits together with its effects, so a crash resumes at the last committed step:
- `extract` saves the validated actions; a restart does not call the extractor again.
- `store` creates drafts and advances `stored_count` in one transaction; a crash rolls both back,
  and the draft fingerprint makes a repeated proposal a `duplicate` instead of a second draft.

Capture is off by default. A job is queued only when the owner has enabled capture and chosen a
capture model; the caller passes the extractor when it runs jobs. Extraction calls carry no tools.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Any, Callable, Protocol
from uuid import UUID

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from nexus_core.platform import Principal, new_id, utc_now
from nexus_memory import capture as rules
from nexus_memory import service as memory_rules
from nexus_memory.ports import MemoryConflict
from nexus_platform.authz.audit import audit
from nexus_platform.errors import PlatformError
from nexus_platform.models.provider_settings import authorize_model, context
from nexus_platform.persistence.models import (
    MemoryCaptureCursorRecord,
    MemoryCaptureJobRecord,
    MemoryCaptureSettingsRecord,
    MemoryDraftRecord,
    MemoryEntryRecord,
    MemoryVersionRecord,
    AgentVersionRecord,
    MessageRecord,
    RunRecord,
)

from .repository import SqlMemoryRepository
from .switches import memory_state

#: Lease length for a claimed job. A job whose lease expired is taken over by the next claim.
LEASE = timedelta(minutes=5)
#: Job states that still need work. One unfinished job per owner is allowed at a time.
UNFINISHED = ('pending', 'extracted', 'stored')
#: Messages read when planning one window; the topic split and window cap apply to this list.
PLAN_MESSAGE_LIMIT = 200


CAPACITY_POLICIES = ('reject', 'evict_auto')


class Extractor(Protocol):
    """Model-backed extraction: receives the window, related entries, the capture model version and the
    owner's tenant and id (the caller resolves the owner's key from these), and returns raw action items.
    It runs outside any database transaction.

    Implementations must not attach tools to the model call. A raised exception is a failed attempt
    with a stable code; the raw output is not stored when it fails.
    """

    def __call__(self, *, messages: list[rules.Message], related: list[dict[str, Any]], model_version_id: UUID,
                 tenant_id: UUID, owner_id: UUID) -> Any: ...


# ---------------------------------------------------------------- settings

def set_capture(db: Session, principal: Principal, tenant_id: UUID, *, enabled: bool,
                model_profile_version_id: UUID | None, capacity_policy: str = 'reject') -> dict[str, Any]:
    """Turn capture on or off for the caller in this space. Enabling requires a capture model.

    `capacity_policy` decides what happens when the memory budget is full: `reject` (default) refuses
    the draft; `evict_auto` archives the caller's oldest capture-origin entries to make room.
    """
    if enabled and model_profile_version_id is None:
        raise ValueError('A capture model is required to enable automatic capture')
    if capacity_policy not in CAPACITY_POLICIES:
        raise ValueError('Capacity policy is invalid')
    with db.begin():
        user, _ = context(db, principal, tenant_id)
        row = db.get(MemoryCaptureSettingsRecord, (tenant_id, user.id))
        if row is None:
            row = MemoryCaptureSettingsRecord(tenant_id=tenant_id, owner_user_id=user.id)
            db.add(row)
        row.enabled = enabled
        row.model_profile_version_id = model_profile_version_id
        row.capacity_policy = capacity_policy
        row.updated_at = utc_now()
        audit(db, tenant_id, user.id, 'memory.capture_settings', 'memory_capture', str(user.id),
              {'enabled': enabled, 'capacity_policy': capacity_policy})
        return _view(row)


def capture_settings(db: Session, principal: Principal, tenant_id: UUID) -> dict[str, Any]:
    """Current settings; defaults to disabled when the caller never changed them."""
    with db.begin():
        user, _ = context(db, principal, tenant_id)
        row = db.get(MemoryCaptureSettingsRecord, (tenant_id, user.id))
        if row is None:
            return {'enabled': False, 'model_profile_version_id': None, 'capacity_policy': 'reject'}
        return _view(row)


def _view(row: MemoryCaptureSettingsRecord) -> dict[str, Any]:
    return {'enabled': row.enabled,
            'model_profile_version_id': str(row.model_profile_version_id) if row.model_profile_version_id else None,
            'capacity_policy': row.capacity_policy}


# ---------------------------------------------------------------- enqueue

def enqueue_for_run(db: Session, run: RunRecord, *, now: datetime | None = None) -> str | None:
    """Queue a capture job for a completed Run, inside the Run's completion transaction.

    Returns the job id, or None when nothing was queued: capture is off, no capture model is set,
    the owner already has an unfinished job (its messages stay unread and the next Run picks them up),
    or no unread window is ready. Nothing is queued unless the owner has opted in.
    """
    now = now or utc_now()
    settings = db.get(MemoryCaptureSettingsRecord, (run.tenant_id, run.principal_id))
    if settings is None or not settings.enabled or settings.model_profile_version_id is None:
        return None
    # Memory switches (openspec 2026-11-05-memory-switches): nothing is queued, and the cursor stays where
    # it is, while memory is off for the space, the member or this Run's agent, or the space is `explicit`.
    if not memory_state(db, tenant_id=run.tenant_id, owner_id=run.principal_id,
                        agent_budgets=_run_budgets(db, run)).capture_allowed:
        return None
    busy = db.scalar(select(MemoryCaptureJobRecord.id).where(
        MemoryCaptureJobRecord.tenant_id == run.tenant_id,
        MemoryCaptureJobRecord.owner_user_id == run.principal_id,
        MemoryCaptureJobRecord.state.in_(UNFINISHED)).limit(1))
    if busy is not None:
        return None
    cursor = db.get(MemoryCaptureCursorRecord, run.session_id)
    if cursor is None:
        cursor = MemoryCaptureCursorRecord(session_id=run.session_id, tenant_id=run.tenant_id,
                                           owner_user_id=run.principal_id, last_processed_sequence=0,
                                           updated_at=now)
        db.add(cursor)
        db.flush()
    rows = db.scalars(select(MessageRecord).where(
        MessageRecord.session_id == run.session_id, MessageRecord.sequence > cursor.last_processed_sequence)
        .order_by(MessageRecord.sequence).limit(PLAN_MESSAGE_LIMIT)).all()
    messages = [rules.Message(sequence=m.sequence, role=m.role, content=m.content,
                              created_at=m.created_at, id=str(m.id)) for m in rows]
    window = rules.plan_window(messages, cursor=cursor.last_processed_sequence, now=now,
                               last_window_at=cursor.updated_at if cursor.last_processed_sequence else None)
    if window is None:
        return None
    job_id = new_id()
    db.add(MemoryCaptureJobRecord(
        id=job_id, tenant_id=run.tenant_id, owner_user_id=run.principal_id, session_id=run.session_id,
        source_run_id=run.id, from_sequence=window.from_sequence, through_sequence=window.through_sequence,
        state='pending', available_at=now + rules.CAPTURE_DELAY, attempt_count=0, stored_count=0,
        created_at=now))
    cursor.last_processed_sequence = window.through_sequence
    cursor.updated_at = now
    return str(job_id)


# ---------------------------------------------------------------- claim

def claim_next(db: Session, *, worker_id: str, now: datetime | None = None) -> UUID | None:
    """Lease the next due job. The claim is a conditional UPDATE, so two workers cannot both win.

    A job is due when `available_at` has passed and it is not leased (or its lease expired, which
    is how a crashed worker's job is taken over).
    """
    now = now or utc_now()
    candidates = db.scalars(select(MemoryCaptureJobRecord.id).where(
        MemoryCaptureJobRecord.state.in_(UNFINISHED),
        MemoryCaptureJobRecord.available_at <= now,
        or_(MemoryCaptureJobRecord.lease_expires_at.is_(None), MemoryCaptureJobRecord.lease_expires_at < now))
        .order_by(MemoryCaptureJobRecord.available_at).limit(5)).all()
    for job_id in candidates:
        won = db.execute(update(MemoryCaptureJobRecord).where(
            MemoryCaptureJobRecord.id == job_id,
            MemoryCaptureJobRecord.state.in_(UNFINISHED),
            or_(MemoryCaptureJobRecord.lease_expires_at.is_(None), MemoryCaptureJobRecord.lease_expires_at < now))
            .values(lease_owner=worker_id, lease_expires_at=now + LEASE)).rowcount
        if won == 1:
            return job_id
    return None


# ---------------------------------------------------------------- state machine

def run_step(factory: Callable[[], Session], job_id: UUID, extractor: Extractor, *,
             now: datetime | None = None) -> str:
    """Perform the job's next step and return the resulting state.

    Each step commits on its own. The extraction step runs in three phases so the model call (and the
    credential lookup it needs) happens outside any open transaction: plan (read), call, record (write).
    A failing step is rolled back and recorded as a failed attempt in a second transaction.
    """
    now = now or utc_now()
    try:
        if _is_pending(factory, job_id):
            return _extraction_step(factory, job_id, extractor, now)
        with factory() as db, db.begin():
            job = db.get(MemoryCaptureJobRecord, job_id, with_for_update=True)
            if job is None or job.state not in UNFINISHED:
                return job.state if job else 'missing'
            if job.state == 'extracted':
                _store(db, job, now)
            else:
                _finish(db, job, now)
            return job.state
    except Exception as exc:  # noqa: BLE001  (every failure becomes a stable code on the job)
        with factory() as db, db.begin():
            job = db.get(MemoryCaptureJobRecord, job_id, with_for_update=True)
            if job is None:
                return 'missing'
            _record_failure(job, _failure_code(exc), now)
            return job.state


def run_due(factory: Callable[[], Session], extractor: Extractor, *, worker_id: str,
            now: datetime | None = None) -> str | None:
    """Claim one due job and run its steps until it completes, fails, or waits for backoff.

    Returns the job's last state, or None when no job was due. Each call is a worker tick; a
    crash between steps leaves the job at its last committed state.
    """
    now = now or utc_now()
    with factory() as db, db.begin():
        job_id = claim_next(db, worker_id=worker_id, now=now)
    if job_id is None:
        return None
    state = 'pending'
    while state in UNFINISHED:
        state = run_step(factory, job_id, extractor, now=now)
        if state in UNFINISHED and _job_waiting(factory, job_id, now):
            break
    return state


def _job_waiting(factory: Callable[[], Session], job_id: UUID, now: datetime) -> bool:
    """True when the job is unfinished but not yet due again (backoff)."""
    with factory() as db, db.begin():
        job = db.get(MemoryCaptureJobRecord, job_id)
        return job is not None and job.state in UNFINISHED and rules.aware(job.available_at) > rules.aware(now)


def _is_pending(factory: Callable[[], Session], job_id: UUID) -> bool:
    with factory() as db:
        job = db.get(MemoryCaptureJobRecord, job_id)
        return job is not None and job.state == 'pending'


@dataclass(frozen=True)
class _Plan:
    """What the extraction call needs, read before the call. `skip` names why there is no call."""
    skip: str | None
    messages: list[rules.Message]
    related: list[dict[str, Any]]
    version_id: UUID | None
    tenant_id: UUID
    owner_id: UUID


def _plan(db: Session, job: MemoryCaptureJobRecord) -> _Plan:
    """Read-only: settings, model authorization, window messages and related entries."""
    empty = _Plan('', [], [], None, job.tenant_id, job.owner_user_id)
    settings = db.get(MemoryCaptureSettingsRecord, (job.tenant_id, job.owner_user_id))
    if settings is None or not settings.enabled or settings.model_profile_version_id is None:
        return replace(empty, skip='capture_disabled')
    # A job queued before a switch was turned off completes without a model call.
    source_run = db.get(RunRecord, job.source_run_id)
    if not memory_state(db, tenant_id=job.tenant_id, owner_id=job.owner_user_id,
                        agent_budgets=_run_budgets(db, source_run) if source_run else None).capture_allowed:
        return replace(empty, skip='memory_disabled')
    version_id = settings.model_profile_version_id
    try:
        authorize_model(db, job.tenant_id, job.owner_user_id, version_id)
    except PlatformError:
        return replace(empty, skip='model_unavailable')
    rows = db.scalars(select(MessageRecord).where(
        MessageRecord.session_id == job.session_id,
        MessageRecord.sequence >= job.from_sequence, MessageRecord.sequence <= job.through_sequence)
        .order_by(MessageRecord.sequence)).all()
    messages = [rules.Message(sequence=m.sequence, role=m.role, content=m.content,
                              created_at=m.created_at, id=str(m.id)) for m in rows]
    repo = SqlMemoryRepository(db)
    related = [{'id': str(e.id), 'title': e.title, 'kind': e.kind}
               for e in repo.published_entries(job.tenant_id, job.owner_user_id, '')[:rules.RELATED_LIMIT]]
    return _Plan(None, messages, related, version_id, job.tenant_id, job.owner_user_id)


def _extraction_step(factory: Callable[[], Session], job_id: UUID, extractor: Extractor, now: datetime) -> str:
    """Plan, call the model outside any transaction, then record the validated output."""
    with factory() as db:
        job = db.get(MemoryCaptureJobRecord, job_id)
        if job is None or job.state != 'pending':
            return job.state if job else 'missing'
        plan = _plan(db, job)
    if plan.skip:
        return _complete_skipped(factory, job_id, plan.skip, now)
    try:
        raw = extractor(messages=plan.messages, related=plan.related, model_version_id=plan.version_id,
                        tenant_id=plan.tenant_id, owner_id=plan.owner_id)
    except PlatformError:
        # The owner's key or the model stopped being usable between planning and the call.
        return _complete_skipped(factory, job_id, 'model_unavailable', now)
    with factory() as db, db.begin():
        job = db.get(MemoryCaptureJobRecord, job_id, with_for_update=True)
        if job is None or job.state != 'pending':
            return job.state if job else 'missing'
        _record_extraction(db, job, raw)
        return job.state


def _complete_skipped(factory: Callable[[], Session], job_id: UUID, reason: str, now: datetime) -> str:
    with factory() as db, db.begin():
        job = db.get(MemoryCaptureJobRecord, job_id, with_for_update=True)
        if job is None or job.state != 'pending':
            return job.state if job else 'missing'
        _skip(db, job, reason, now)
        return job.state


def _record_extraction(db: Session, job: MemoryCaptureJobRecord, raw: Any) -> None:
    """Keep only validated actions; invalid items are counted and their reasons audited, never stored."""
    verdict = rules.validate_actions(raw, unattended=True)
    job.actions = [_serialize(action) for action in verdict.actions]
    job.state = 'extracted'
    job.last_error = None
    audit(db, job.tenant_id, job.owner_user_id, 'memory.capture', 'memory_capture_job', str(job.id),
          {'step': 'extract', 'calls': 1, 'actions': len(verdict.actions), 'rejected': verdict.rejected,
           'reasons': verdict.reasons[:5]})


def _skip(db: Session, job: MemoryCaptureJobRecord, reason: str, now: datetime) -> None:
    job.actions = []
    job.state = 'completed'
    job.completed_at = now
    job.last_error = reason
    job.lease_owner = None
    job.lease_expires_at = None
    audit(db, job.tenant_id, job.owner_user_id, 'memory.capture', 'memory_capture_job', str(job.id),
          {'step': 'skip', 'reason': reason})


def _store(db: Session, job: MemoryCaptureJobRecord, now: datetime) -> None:
    """Create drafts for actions not yet stored. `stored_count` is the index of the next action."""
    repo = SqlMemoryRepository(db)
    actions = list(job.actions or [])
    source_ids = _source_message_ids(db, job)
    settings = db.get(MemoryCaptureSettingsRecord, (job.tenant_id, job.owner_user_id))
    policy = settings.capacity_policy if settings else 'reject'
    results: list[str] = []
    evicted = 0
    for index in range(job.stored_count, len(actions)):
        action = actions[index]
        try:
            outcome = _propose(repo, job, action, source_ids)
            if outcome['status'] == 'budget_exceeded' and policy == 'evict_auto':
                freed = _evict_capture_entries(db, job, needed=_shortfall(outcome))
                evicted += freed
                if freed:
                    outcome = _propose(repo, job, action, source_ids)
        except MemoryConflict:
            outcome = {'status': 'conflict'}
        results.append(outcome['status'])
        job.stored_count = index + 1
    job.state = 'stored'
    job.last_error = None
    audit(db, job.tenant_id, job.owner_user_id, 'memory.capture', 'memory_capture_job', str(job.id),
          {'step': 'store', 'drafts': results.count('pending'), 'duplicates': results.count('duplicate'),
           'other': len(results) - results.count('pending') - results.count('duplicate'),
           'evicted': evicted, 'policy': policy, 'statuses': results[:10]})


def _propose(repo: SqlMemoryRepository, job: MemoryCaptureJobRecord, action: dict[str, Any],
             source_ids: tuple[str, ...]) -> dict[str, Any]:
    return memory_rules.propose(
        repo, job.tenant_id, job.owner_user_id, job.source_run_id, action.get('kind', 'memory'),
        action['diff'], entry_id=_uuid_or_none(action.get('entry_id')),
        base_version=action.get('base_version'), origin='capture', source_message_ids=source_ids)


def _shortfall(outcome: dict[str, Any]) -> int:
    """Characters that must be freed before the refused content fits: `used + needed - budget`."""
    return int(outcome['used']) + int(outcome['needed']) - int(outcome['budget'])


def _evict_capture_entries(db: Session, job: MemoryCaptureJobRecord, *, needed: int) -> int:
    """Archive the owner's oldest capture-origin entries until `needed` characters are freed.

    Only entries whose current version came from a capture draft are candidates; hand-written
    entries are never evicted. Archiving keeps the immutable history. Returns characters freed.
    """
    if needed <= 0:
        return 0
    repo = SqlMemoryRepository(db)
    sizes = {entry.id: entry.chars for entry in repo.sized_entries(job.tenant_id, job.owner_user_id)}
    candidates = db.execute(
        select(MemoryEntryRecord.id)
        .join(MemoryVersionRecord, (MemoryVersionRecord.entry_id == MemoryEntryRecord.id)
              & (MemoryVersionRecord.version == MemoryEntryRecord.current_version))
        .join(MemoryDraftRecord, MemoryDraftRecord.id == MemoryVersionRecord.source_draft_id)
        .where(MemoryEntryRecord.tenant_id == job.tenant_id, MemoryEntryRecord.owner_user_id == job.owner_user_id,
               MemoryEntryRecord.active.is_(True), MemoryDraftRecord.origin == 'capture')
        .order_by(MemoryVersionRecord.created_at)).scalars().all()
    freed = 0
    for entry_id in candidates:
        if freed >= needed:
            break
        memory_rules.archive(repo, job.owner_user_id, job.tenant_id, entry_id)
        # Flush so the budget recount below (a fresh query) no longer counts the archived entry.
        db.flush()
        freed += sizes.get(entry_id, 0)
    return freed


def _finish(db: Session, job: MemoryCaptureJobRecord, now: datetime) -> None:
    job.state = 'completed'
    job.completed_at = now
    job.lease_owner = None
    job.lease_expires_at = None


def _record_failure(job: MemoryCaptureJobRecord, code: str, now: datetime) -> None:
    """Count a failed attempt, release the lease, and either back off or give up.

    A failure does not move the state, so the next attempt repeats the same step. Only the step
    that failed runs again; earlier steps are already committed.
    """
    job.attempt_count += 1
    job.last_error = code[:500]
    job.lease_owner = None
    job.lease_expires_at = None
    if job.attempt_count >= rules.MAX_ATTEMPTS:
        job.state = 'failed'
        job.completed_at = now
        job.next_retry_at = None
        return
    wait = timedelta(seconds=rules.backoff_seconds(job.attempt_count))
    job.next_retry_at = now + wait
    job.available_at = now + wait


def _failure_code(exc: Exception) -> str:
    """Stable code for a failure. Exception text is not stored, because it may contain model output."""
    if isinstance(exc, MemoryConflict):
        return 'memory_conflict'
    return 'step_error'


def _source_message_ids(db: Session, job: MemoryCaptureJobRecord) -> tuple[str, ...]:
    rows = db.scalars(select(MessageRecord.id).where(
        MessageRecord.session_id == job.session_id,
        MessageRecord.sequence >= job.from_sequence, MessageRecord.sequence <= job.through_sequence)
        .order_by(MessageRecord.sequence)).all()
    return tuple(str(row) for row in rows)


def _serialize(action: dict[str, Any]) -> dict[str, Any]:
    """JSON-safe copy of a validated action for the job's `actions` column."""
    out = dict(action)
    if isinstance(out.get('entry_id'), UUID):
        out['entry_id'] = str(out['entry_id'])
    return out


def _uuid_or_none(value: Any) -> UUID | None:
    return UUID(value) if isinstance(value, str) else value


def _run_budgets(db: Session, run: RunRecord) -> dict[str, Any] | None:
    """Budgets of the agent version the Run used, for the agent's memory switch; None when unknown."""
    version_id = (run.config_snapshot or {}).get('agent_version_id')
    if not version_id:
        return None
    version = db.get(AgentVersionRecord, UUID(str(version_id)))
    return version.budgets if version else None
