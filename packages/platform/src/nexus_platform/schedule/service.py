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
from nexus_platform.orgs.access import is_space_manager
from nexus_platform.persistence.models import AgentRecord, AgentVersionRecord, RunRecord, UserRecord
from nexus_platform.identity.service import principal_for_user, require_membership, require_tenant, resolve_user
from nexus_platform.persistence.models.schedule import CronJobRecord
from .rules import Rule, ScheduleError, next_after, parse, zone

MAX_ACTIVE_JOBS = 10
MAX_PROMPT_CHARS = 4000
#: A manual run is refused when the previous run (manual or scheduled) started less than this many seconds ago.
RUN_NOW_MIN_SECONDS = 60
PREVIEW_MAX = 5
RUNS_MAX = 50
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


def _owned(db: Session, user_id: UUID, tenant_id: UUID, job_id: str, *, manager_may_see: bool = False) -> CronJobRecord:
    """The caller's own job. With ``manager_may_see`` a space owner or admin also gets other people's jobs (read and
    pause only); everyone else, and any other job, is reported as not found so ids cannot be probed."""
    try:
        job = db.get(CronJobRecord, UUID(job_id))
    except ValueError:
        job = None
    if job is None or job.tenant_id != tenant_id:
        raise ScheduleError('schedule_not_found', 'no such scheduled task')
    if job.owner_user_id != user_id and not (manager_may_see and is_space_manager(db, tenant_id, user_id)):
        raise ScheduleError('schedule_not_found', 'no such scheduled task')
    return job


def change_state(db: Session, principal: Principal, tenant_id: UUID, job_id: str, action: str) -> dict:
    """`pause`, `resume` or `delete` a job owned by the caller."""
    with db.begin():
        user = resolve_user(db, principal)
        require_membership(db, tenant_id, user.id)
        job = _owned(db, user.id, tenant_id, job_id, manager_may_see=action == 'pause')
        if job.owner_user_id != user.id:
            # A space owner or admin may only pause somebody else's task (the owner resumes it).
            job.state = 'paused'
            audit(db, tenant_id, user.id, 'schedule.paused', 'cron_job', job_id, {'by_manager': True, 'owner': str(job.owner_user_id)})
            return _view(job)
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


# ---------------------------------------------------------------- REST support (design 8.2a)

def _detail(db: Session, job: CronJobRecord) -> dict:
    """The list view plus what the page needs: the prompt, the rule, the pinned agent version and the owner."""
    version = db.get(AgentVersionRecord, job.agent_version_id)
    agent = db.get(AgentRecord, version.agent_id) if version else None
    owner = db.get(UserRecord, job.owner_user_id)
    return _view(job) | {
        'prompt': job.prompt, 'rule': job.rule, 'session_id': str(job.session_id), 'created_at': job.created_at.isoformat(),
        'last_run_id': str(job.last_run_id) if job.last_run_id else None,
        'agent_id': str(agent.id) if agent else None, 'agent_name': agent.name if agent else '',
        'agent_version': version.version if version else None,
        'owner_user_id': str(job.owner_user_id), 'owner_name': getattr(owner, 'display_name', None) or '',
    }


def _member(db: Session, principal: Principal, tenant_id: UUID) -> UUID:
    user = resolve_user(db, principal)
    require_tenant(db, tenant_id)
    require_membership(db, tenant_id, user.id)
    return user.id


def list_jobs_detailed(db: Session, principal: Principal, tenant_id: UUID, scope: str = 'mine') -> list[dict]:
    """``mine``: the caller's tasks. ``all``: every task of the space, for its owners and admins only."""
    if scope not in ('mine', 'all'):
        raise ScheduleError('schedule_invalid', 'scope must be mine or all')
    with db.begin():
        user_id = _member(db, principal, tenant_id)
        query = select(CronJobRecord).where(CronJobRecord.tenant_id == tenant_id)
        if scope == 'all':
            if not is_space_manager(db, tenant_id, user_id):
                raise ScheduleError('schedule_forbidden', 'only a space owner or admin can list everyone\'s tasks')
        else:
            query = query.where(CronJobRecord.owner_user_id == user_id)
        return [_detail(db, job) for job in db.scalars(query.order_by(CronJobRecord.created_at)).all()]


def get_job(db: Session, principal: Principal, tenant_id: UUID, job_id: str) -> dict:
    with db.begin():
        user_id = _member(db, principal, tenant_id)
        return _detail(db, _owned(db, user_id, tenant_id, job_id, manager_may_see=True))


def create_job_for_agent(db: Session, principal: Principal, tenant_id: UUID, *, agent_id: UUID, name: str, prompt: str,
                         rule: dict, timezone_name: str) -> dict:
    """Create a job on the agent's current published version (the REST entry; the tools pass a version directly)."""
    with db.begin():
        _member(db, principal, tenant_id)
        agent = db.scalar(select(AgentRecord).where(AgentRecord.id == agent_id, AgentRecord.tenant_id == tenant_id))
        if agent is None or agent.status == 'archived':
            raise ScheduleError('schedule_agent_not_found', 'no such agent in this space')
        if agent.published_version_id is None:
            raise ScheduleError('schedule_agent_unpublished', 'the agent has no published version yet')
        version_id = agent.published_version_id
    created = create_job(db, principal, tenant_id, agent_version_id=version_id, name=name, prompt=prompt, rule=rule,
                         timezone_name=timezone_name)
    with db.begin():
        return _detail(db, db.get(CronJobRecord, UUID(created['id'])))


def update_job(db: Session, principal: Principal, tenant_id: UUID, job_id: str, *, name: str | None = None,
               prompt: str | None = None, rule: dict | None = None, timezone_name: str | None = None) -> dict:
    """Change an own task. A new rule or time zone recomputes the next run from now; a new prompt is scanned again.
    A suspended task stays suspended until it is resumed."""
    if name is not None:
        name = name.strip()
        if not name or len(name) > 120:
            raise ScheduleError('schedule_name_invalid', 'a name of up to 120 characters is required')
    if prompt is not None:
        prompt = prompt.strip()
        if not prompt or len(prompt) > MAX_PROMPT_CHARS:
            raise ScheduleError('schedule_prompt_invalid', f'the prompt must be 1-{MAX_PROMPT_CHARS} characters')
        _scan(prompt)
    parsed = parse(rule) if rule is not None else None
    if timezone_name is not None:
        zone(timezone_name)
    with db.begin():
        user_id = _member(db, principal, tenant_id)
        job = _owned(db, user_id, tenant_id, job_id)
        if name is not None:
            job.name = name
        if prompt is not None:
            job.prompt = prompt
        timing = parsed is not None or (timezone_name is not None and timezone_name != job.timezone)
        if parsed is not None:
            job.rule = parsed.as_dict()
        if timezone_name is not None:
            job.timezone = timezone_name
        if timing and job.state == 'active':
            job.next_run_at = next_after(parse(job.rule), zone(job.timezone), utc_now())
        audit(db, tenant_id, user_id, 'schedule.updated', 'cron_job', job_id,
              {'fields': [key for key, value in (('name', name), ('prompt', prompt), ('rule', rule), ('timezone', timezone_name)) if value is not None]})
        return _detail(db, job)


def run_now(db: Session, principal: Principal, tenant_id: UUID, job_id: str, now: datetime | None = None) -> dict:
    """Start one run of an own task right away. The schedule is untouched; a second click within a minute is refused."""
    from nexus_platform.runs.compatibility import create_run
    now = now or utc_now()
    with db.begin():
        user_id = _member(db, principal, tenant_id)
        job = _owned(db, user_id, tenant_id, job_id)
        last = job.last_run_at.replace(tzinfo=now.tzinfo) if job.last_run_at and job.last_run_at.tzinfo is None else job.last_run_at
        if last is not None and (now - last).total_seconds() < RUN_NOW_MIN_SECONDS:
            raise ScheduleError('schedule_run_too_soon', f'wait {RUN_NOW_MIN_SECONDS} seconds between runs')
        session_id, prompt = job.session_id, job.prompt
    run, _ = create_run(db, principal, tenant_id, session_id, message=prompt, idempotency_key=f'cron-now:{job_id}:{new_id()}')
    with db.begin():
        job = db.get(CronJobRecord, UUID(job_id))
        job.last_run_at, job.last_run_id, job.run_count = now, run.id, job.run_count + 1
        audit(db, tenant_id, user_id, 'schedule.run_now', 'cron_job', job_id, {'run_id': str(run.id)})
        return _detail(db, job)


def list_runs(db: Session, principal: Principal, tenant_id: UUID, job_id: str, limit: int = 20) -> list[dict]:
    """Runs of the task's own session, newest first. Readable by the owner and by space owners and admins."""
    limit = max(1, min(int(limit), RUNS_MAX))
    with db.begin():
        user_id = _member(db, principal, tenant_id)
        job = _owned(db, user_id, tenant_id, job_id, manager_may_see=True)
        rows = db.scalars(select(RunRecord).where(RunRecord.session_id == job.session_id, RunRecord.tenant_id == tenant_id)
                          .order_by(RunRecord.created_at.desc()).limit(limit)).all()
        return [{'id': str(run.id), 'status': run.status, 'created_at': run.created_at.isoformat(),
                 'started_at': run.started_at.isoformat() if run.started_at else None,
                 'ended_at': run.ended_at.isoformat() if run.ended_at else None,
                 'error_code': run.error_code or '', 'session_id': str(job.session_id),
                 'cancel_requested': run.cancel_requested_at is not None} for run in rows]


def preview(rule: dict, timezone_name: str, count: int = 3, now: datetime | None = None) -> list[str]:
    """The next fire times of a rule in UTC (ISO strings), without writing anything. Raises ScheduleError."""
    parsed, tz = parse(rule), zone(timezone_name)
    moment, times = now or utc_now(), []
    for _ in range(max(1, min(int(count), PREVIEW_MAX))):
        moment = next_after(parsed, tz, moment)
        times.append(moment.isoformat())
    return times
