"""Scheduled runs: create, list, pause, resume, delete, and fire what is due (openspec 2026-11-07-tool-expansion 8.2).

Rules the service enforces, whatever created the job:

- the job runs as its owner, on the agent version it was created for, in its own session;
- there is a limit on active jobs per owner and a shortest interval, so a job cannot flood the queue;
- the prompt is scanned for injection phrasing before it is stored, because it will run later with nobody watching;
- a job is suspended, not retried forever, when its owner, space or agent can no longer run it.

Runs a job starts are unattended: the worker withholds approvals and questions from them (see
`is_scheduled_session`).
"""
from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from nexus_core.platform import Principal, new_id, utc_now
from nexus_platform.authz.audit import audit
from nexus_platform.errors import PlatformError
from nexus_platform.identity.service import principal_for_user, require_membership, require_tenant, resolve_user
from nexus_platform.persistence.models.schedule import CronJobRecord
from .rules import Rule, ScheduleError, next_after, parse, zone

MAX_ACTIVE_JOBS = 10
MAX_PROMPT_CHARS = 4000
#: Due jobs handled by one scheduler tick.
TICK_BATCH = 20


def _view(job: CronJobRecord) -> dict:
    rule = parse(job.rule)
    return {'id': str(job.id), 'name': job.name, 'schedule': rule.describe(), 'timezone': job.timezone, 'state': job.state,
            'next_run_at': job.next_run_at.isoformat(), 'last_run_at': job.last_run_at.isoformat() if job.last_run_at else None,
            'run_count': job.run_count, 'last_error': job.last_error}


def _scan(prompt: str) -> None:
    """Refuse prompts that look like injected instructions. The scanner lives with the tools; absent means no scan."""
    try:
        from nexus_tools.threats import scan
    except ImportError:
        return
    if scan(prompt):
        raise ScheduleError('schedule_prompt_suspicious', 'the prompt contains phrasing that looks like an injected instruction')


def create_job(db: Session, principal: Principal, tenant_id: UUID, *, agent_version_id: UUID, name: str, prompt: str,
               rule: dict, timezone_name: str) -> dict:
    """Create a job and its session. Raises ScheduleError or PlatformError."""
    from nexus_platform.sessions.service import create_session
    parsed = parse(rule)
    tz = zone(timezone_name)
    name, prompt = name.strip(), prompt.strip()
    if not name or len(name) > 120:
        raise ScheduleError('schedule_name_invalid', 'a name of up to 120 characters is required')
    if not prompt or len(prompt) > MAX_PROMPT_CHARS:
        raise ScheduleError('schedule_prompt_invalid', f'the prompt must be 1-{MAX_PROMPT_CHARS} characters')
    _scan(prompt)
    with db.begin():
        user = resolve_user(db, principal)
        require_tenant(db, tenant_id)
        require_membership(db, tenant_id, user.id)
        active = len(db.scalars(select(CronJobRecord.id).where(
            CronJobRecord.tenant_id == tenant_id, CronJobRecord.owner_user_id == user.id, CronJobRecord.state == 'active')).all())
    if active >= MAX_ACTIVE_JOBS:
        raise ScheduleError('schedule_limit_reached', f'at most {MAX_ACTIVE_JOBS} active scheduled tasks per person')
    session = create_session(db, principal, tenant_id, agent_version_id=agent_version_id, title=f'[定时] {name}')
    now = utc_now()
    with db.begin():
        job = CronJobRecord(id=new_id(), tenant_id=tenant_id, owner_user_id=user.id, agent_version_id=agent_version_id,
                            session_id=session.id, name=name, prompt=prompt, rule=parsed.as_dict(), timezone=timezone_name,
                            state='active', next_run_at=next_after(parsed, tz, now), created_at=now)
        db.add(job)
        db.flush()
        audit(db, tenant_id, user.id, 'schedule.created', 'cron_job', str(job.id), {'rule': parsed.as_dict()})
        return _view(job)


def list_jobs(db: Session, principal: Principal, tenant_id: UUID) -> list[dict]:
    with db.begin():
        user = resolve_user(db, principal)
        require_membership(db, tenant_id, user.id)
        jobs = db.scalars(select(CronJobRecord).where(CronJobRecord.tenant_id == tenant_id, CronJobRecord.owner_user_id == user.id)
                          .order_by(CronJobRecord.created_at)).all()
        return [_view(job) for job in jobs]


def _owned(db: Session, user_id: UUID, tenant_id: UUID, job_id: str) -> CronJobRecord:
    try:
        job = db.get(CronJobRecord, UUID(job_id))
    except ValueError:
        job = None
    if job is None or job.tenant_id != tenant_id or job.owner_user_id != user_id:
        raise ScheduleError('schedule_not_found', 'no such scheduled task')
    return job


def change_state(db: Session, principal: Principal, tenant_id: UUID, job_id: str, action: str) -> dict:
    """`pause`, `resume` or `delete` a job owned by the caller."""
    with db.begin():
        user = resolve_user(db, principal)
        require_membership(db, tenant_id, user.id)
        job = _owned(db, user.id, tenant_id, job_id)
        if action == 'delete':
            view = _view(job)
            db.delete(job)
            audit(db, tenant_id, user.id, 'schedule.deleted', 'cron_job', job_id, {})
            return view | {'state': 'deleted'}
        if action == 'pause':
            job.state = 'paused'
        elif action == 'resume':
            active = len(db.scalars(select(CronJobRecord.id).where(
                CronJobRecord.tenant_id == tenant_id, CronJobRecord.owner_user_id == user.id, CronJobRecord.state == 'active')).all())
            if job.state != 'active' and active >= MAX_ACTIVE_JOBS:
                raise ScheduleError('schedule_limit_reached', f'at most {MAX_ACTIVE_JOBS} active scheduled tasks per person')
            job.state, job.last_error = 'active', ''
            job.next_run_at = next_after(parse(job.rule), zone(job.timezone), utc_now())
        else:
            raise ScheduleError('schedule_action_invalid', 'action must be pause, resume or delete')
        audit(db, tenant_id, user.id, f'schedule.{action}d', 'cron_job', job_id, {})
        return _view(job)


def is_scheduled_session(factory: sessionmaker, session_id: UUID) -> bool:
    """Whether runs of this session are started by the scheduler (and therefore have nobody to approve or answer)."""
    try:
        with factory() as db:
            return db.scalar(select(CronJobRecord.id).where(CronJobRecord.session_id == session_id).limit(1)) is not None
    except SQLAlchemyError:
        return False  # the table does not exist yet (migration not applied), so no job can own this session


def fire_due(factory: sessionmaker, now: datetime | None = None) -> int:
    """Start the Run of every due active job; returns how many were started or suspended.

    The next fire time is stored first, with a conditional update, so two workers never start the same fire and
    a crash after it loses at most one fire instead of repeating it. Jobs more than one period late fire once and
    skip the missed ones. The run key makes a retried submission idempotent.
    """
    from nexus_platform.runs.compatibility import create_run
    now = now or utc_now()
    handled = 0
    with factory() as db:
        due = db.execute(select(CronJobRecord.id, CronJobRecord.next_run_at).where(
            CronJobRecord.state == 'active', CronJobRecord.next_run_at <= now).order_by(CronJobRecord.next_run_at).limit(TICK_BATCH)).all()
    for job_id, scheduled in due:
        with factory() as db:
            with db.begin():
                job = db.get(CronJobRecord, job_id)
                following = next_after(parse(job.rule), zone(job.timezone), now)
                claimed = db.execute(update(CronJobRecord).where(CronJobRecord.id == job_id, CronJobRecord.next_run_at == scheduled,
                                                                 CronJobRecord.state == 'active')
                                     .values(next_run_at=following, last_run_at=now)).rowcount
                if not claimed:
                    continue  # another worker took this fire
                tenant_id, owner_id, session_id, prompt = job.tenant_id, job.owner_user_id, job.session_id, job.prompt
            try:
                with db.begin():
                    principal = principal_for_user(db, owner_id)
                run, _ = create_run(db, principal, tenant_id, session_id, message=prompt,
                                    idempotency_key=f'cron:{job_id}:{scheduled.isoformat()}')
                with db.begin():
                    row = db.get(CronJobRecord, job_id)
                    row.last_run_id, row.run_count, row.last_error = run.id, row.run_count + 1, ''
            except PlatformError as error:
                # The owner, space or agent can no longer run this: stop instead of failing every period.
                with db.begin():
                    row = db.get(CronJobRecord, job_id)
                    row.state, row.last_error = 'suspended', f'{type(error).__name__}'[:120]
                    audit(db, tenant_id, owner_id, 'schedule.suspended', 'cron_job', str(job_id), {'reason': row.last_error}, result='failure')
        handled += 1
    return handled
