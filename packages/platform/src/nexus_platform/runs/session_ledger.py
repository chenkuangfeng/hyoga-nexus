"""Dispatch ledger rules: process epochs, per-session FIFO admissions, CAS claims and recovery.

Every function takes a SQLAlchemy ``Session`` and never commits; the caller owns the
transaction. On SQLite the caller must begin the write with ``BEGIN IMMEDIATE`` so the
read-then-write sequences below are serialized across processes. On PostgreSQL the
conditional ``UPDATE`` statements are sufficient on their own.

Rules (see docs/architecture.md 2.12):

- Each process start increments ``runtime_epoch``. Every mutating call carries the
  caller's epoch; a mismatch raises ``StaleEpoch`` and writes nothing.
- A session's FIFO is ``session_admissions`` ordered by ``seq``. A claim moves the head
  from ``queued`` to ``started`` with a conditional update whose rowcount must be 1.
- A session with any ``started`` or ``unknown`` admission is blocked: no new claim.
- Recovery marks ``started`` rows from an older epoch as ``unknown``. It never replays
  them. ``unknown`` is cleared only by ``resolve_unknown``, an explicit operator action.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import event, func, select, update
from sqlalchemy.orm import Session

from nexus_core.platform import RunStatus, utc_now
from nexus_platform.authz.audit import audit
from nexus_platform.persistence.models.ledger import RuntimeEpochRecord, SessionAdmissionRecord
from nexus_platform.persistence.models.run import RunRecord

#: Maximum queued (not yet claimed) admissions per session. Matches Hermes' ADMISSION_QUEUE_MAX.
ADMISSION_QUEUE_MAX = 32
#: Statuses that hold a deployment-wide session slot: work waiting, executing, or blocked.
_SLOT_STATUSES = ("queued", "started", "unknown")


class LedgerError(RuntimeError):
    """Base class for ledger rejections. Each subclass maps to one stable error code."""

    code = "ledger_error"


class StaleEpoch(LedgerError):
    """The caller's process epoch is no longer current, or its claim was superseded."""

    code = "stale_epoch"


class StaleClaim(LedgerError):
    """A conditional claim matched no row: another writer changed the admission first."""

    code = "stale_claim"


class QueueFull(LedgerError):
    """The session already holds ``ADMISSION_QUEUE_MAX`` queued admissions."""

    code = "queue_full"


class TenantCapacityFull(LedgerError):
    """The tenant already has its maximum number of sessions holding work."""

    code = "tenant_session_limit"


class UserCapacityFull(LedgerError):
    """The user already has their maximum number of sessions holding work."""

    code = "user_session_limit"


class CapacityFull(LedgerError):
    """The deployment already has ``max_sessions`` sessions holding work; a new session is refused."""

    code = "session_capacity_exceeded"


class NotUnknown(LedgerError):
    """``resolve_unknown`` was asked to clear an admission that is not ``unknown``."""

    code = "not_unknown"


class AdmissionNotFound(LedgerError):
    """No admission with the given id exists."""

    code = "admission_not_found"


@dataclass(frozen=True)
class AdmissionView:
    """Plain snapshot of an admission row, safe to use after the session closes."""

    seq: int
    admission_id: UUID
    session_id: UUID
    run_id: UUID
    status: str
    owner_epoch: int | None


def _view(row: SessionAdmissionRecord) -> AdmissionView:
    return AdmissionView(
        seq=row.seq, admission_id=row.admission_id, session_id=row.session_id,
        run_id=row.run_id, status=row.status, owner_epoch=row.owner_epoch,
    )


def begin_process(db: Session, *, instance_id: str, now: datetime) -> int:
    """Start a new process generation: increment the singleton epoch and return it.

    Call once at process startup, before any ledger write. The first call creates the row.
    """
    row = db.scalar(select(RuntimeEpochRecord).where(RuntimeEpochRecord.singleton == 1))
    if row is None:
        row = RuntimeEpochRecord(singleton=1, epoch=1, instance_id=instance_id, started_at=now)
        db.add(row)
    else:
        row.epoch += 1
        row.instance_id = instance_id
        row.started_at = now
    db.flush()
    return row.epoch


def current_epoch(db: Session) -> int:
    """Return the current process epoch, or 0 when no process has started."""
    value = db.scalar(select(RuntimeEpochRecord.epoch).where(RuntimeEpochRecord.singleton == 1))
    return 0 if value is None else value


def require_epoch(db: Session, epoch: int) -> None:
    """Raise ``StaleEpoch`` unless ``epoch`` is the current process epoch.

    Every mutating ledger function calls this first. A process that was superseded by a
    restart therefore cannot write, even if it still holds in-memory state.
    """
    if current_epoch(db) != epoch:
        raise StaleEpoch(f"epoch {epoch} is not current")


def enqueue(
    db: Session, *, session_id: UUID, run_id: UUID, admission_id: UUID, now: datetime,
    max_sessions: int | None = None, max_per_tenant: int | None = None, max_per_user: int | None = None,
) -> AdmissionView:
    """Append an admission to the session FIFO as ``queued``.

    Creation is not fenced: any API or worker process may submit work, and only claims,
    finishes and recovery belong to a process generation. Raises ``QueueFull`` when the
    session already has ``ADMISSION_QUEUE_MAX`` queued rows. The count and insert run in
    the caller's write transaction, so the cap holds under concurrent submissions.

    When ``max_sessions`` is given and this session holds no slot yet, the submission opens a
    new slot. It raises ``CapacityFull`` if ``max_sessions`` distinct sessions already hold one.
    Only submissions check the cap, so a session's later Runs never take a second slot.
    """
    queued = db.scalar(select(func.count()).select_from(SessionAdmissionRecord).where(
        SessionAdmissionRecord.session_id == session_id,
        SessionAdmissionRecord.status == "queued",
    )) or 0
    if queued >= ADMISSION_QUEUE_MAX:
        raise QueueFull(f"session {session_id} has {queued} queued admissions")
    if max_sessions is not None:
        holding = db.scalar(select(func.count()).select_from(SessionAdmissionRecord).where(
            SessionAdmissionRecord.session_id == session_id,
            SessionAdmissionRecord.status.in_(_SLOT_STATUSES),
        )) or 0
        if holding == 0:
            active = db.scalar(select(func.count(func.distinct(SessionAdmissionRecord.session_id))).where(
                SessionAdmissionRecord.status.in_(_SLOT_STATUSES),
            )) or 0
            if active >= max_sessions:
                raise CapacityFull(f"{active} sessions already hold work (limit {max_sessions})")
        if holding == 0 and (max_per_tenant is not None or max_per_user is not None):
            _check_fairness(db, run_id, max_per_tenant, max_per_user)
    row = SessionAdmissionRecord(
        admission_id=admission_id, session_id=session_id, run_id=run_id,
        status="queued", owner_epoch=None, created_at=now, updated_at=now,
    )
    db.add(row)
    db.flush()
    return _view(row)


def _check_fairness(db: Session, run_id: UUID, max_per_tenant: int | None, max_per_user: int | None) -> None:
    """Refuse a new session slot when the Run's tenant or user already holds their limit."""
    run = db.get(RunRecord, run_id)
    if run is None:
        return
    for limit, column, owner, error in (
            (max_per_tenant, RunRecord.tenant_id, run.tenant_id, TenantCapacityFull),
            (max_per_user, RunRecord.principal_id, run.principal_id, UserCapacityFull)):
        if limit is None:
            continue
        held = db.scalar(select(func.count(func.distinct(SessionAdmissionRecord.session_id)))
                         .join(RunRecord, RunRecord.id == SessionAdmissionRecord.run_id)
                         .where(SessionAdmissionRecord.status.in_(_SLOT_STATUSES), column == owner)) or 0
        if held >= limit:
            raise error(f"{held} sessions already hold work (limit {limit})")


def session_blocked(db: Session, session_id: UUID) -> bool:
    """True when the session has a ``started`` or ``unknown`` admission.

    A blocked session cannot be claimed. ``unknown`` blocks until ``resolve_unknown``.
    """
    return db.scalar(select(SessionAdmissionRecord.seq).where(
        SessionAdmissionRecord.session_id == session_id,
        SessionAdmissionRecord.status.in_(("started", "unknown")),
    ).limit(1)) is not None


def claim_next(db: Session, *, epoch: int, session_id: UUID, now: datetime) -> AdmissionView | None:
    """Claim the FIFO head for ``session_id`` and return it, or ``None``.

    Returns ``None`` when the session is blocked or has nothing queued. The claim is a
    conditional update ``WHERE status = 'queued'``; if it matches no row, another writer
    got there first and ``StaleClaim`` is raised so the caller re-reads the queue.
    """
    require_epoch(db, epoch)
    if session_blocked(db, session_id):
        return None
    head = select_head(db, session_id)
    if head is None:
        return None
    return cas_claim(db, head, epoch=epoch, now=now)


def select_head(db: Session, session_id: UUID) -> AdmissionView | None:
    """Read the oldest queued admission of a session without changing it."""
    head = db.scalar(select(SessionAdmissionRecord).where(
        SessionAdmissionRecord.session_id == session_id,
        SessionAdmissionRecord.status == "queued",
    ).order_by(SessionAdmissionRecord.seq).limit(1))
    return None if head is None else _view(head)


def cas_claim(db: Session, head: AdmissionView, *, epoch: int, now: datetime) -> AdmissionView:
    """Move ``head`` from ``queued`` to ``started`` under ``epoch``, or raise ``StaleClaim``.

    The update matches only a row that is still ``queued``. A concurrent claimer that got
    there first makes rowcount 0, and the caller must re-read the queue.
    """
    result = db.execute(update(SessionAdmissionRecord).where(
        SessionAdmissionRecord.admission_id == head.admission_id,
        SessionAdmissionRecord.status == "queued",
    ).values(status="started", owner_epoch=epoch, updated_at=now))
    if result.rowcount != 1:
        raise StaleClaim(f"admission {head.admission_id} was claimed concurrently")
    row = db.scalar(select(SessionAdmissionRecord).where(
        SessionAdmissionRecord.admission_id == head.admission_id,
    ))
    db.refresh(row)
    return _view(row)


#: Run statuses that release the session's admission. Leaving ``unknown`` untouched is the
#: point: a run that the lease path later marks interrupted must not unblock the session.
_RELEASING_STATUSES = ("queued", "started")


def run_admission(db: Session, run_id: UUID) -> AdmissionView | None:
    """Return the admission belonging to ``run_id``, or None for Runs created before the ledger."""
    row = db.scalar(select(SessionAdmissionRecord).where(SessionAdmissionRecord.run_id == run_id))
    return None if row is None else _view(row)


def queue_position(db: Session, run_id: UUID) -> int | None:
    """1-based place of a queued Run in its session FIFO (1 runs next), or None if not queued."""
    row = db.scalar(select(SessionAdmissionRecord).where(
        SessionAdmissionRecord.run_id == run_id, SessionAdmissionRecord.status == "queued",
    ))
    if row is None:
        return None
    return db.scalar(select(func.count()).select_from(SessionAdmissionRecord).where(
        SessionAdmissionRecord.session_id == row.session_id,
        SessionAdmissionRecord.status == "queued",
        SessionAdmissionRecord.seq <= row.seq,
    )) or 0


def claim_run(db: Session, *, epoch: int, run_id: UUID, session_id: UUID, now: datetime) -> bool:
    """Decide whether a Run may execute now, claiming its admission if it is the FIFO head.

    Returns True when the Run may proceed: it was claimed now, it already holds the claim under
    this epoch (resumed after waiting for input), it has no admission (created before the ledger),
    or it is already terminal (the caller completes the delivery). Returns False when the Run must
    wait: it is not the head, the session is blocked by another run, or it is unknown.
    Raises ``StaleEpoch`` when the epoch is not current.
    """
    require_epoch(db, epoch)
    admission = run_admission(db, run_id)
    if admission is None or admission.status == "terminal":
        return True
    if admission.status == "started":
        return admission.owner_epoch == epoch
    if admission.status != "queued" or session_blocked(db, session_id):
        return False
    head = select_head(db, session_id)
    if head is None or head.run_id != run_id:
        return False
    try:
        cas_claim(db, head, epoch=epoch, now=now)
    except StaleClaim:
        return False
    return True


def finish_run(db: Session, *, run_id: UUID, now: datetime) -> None:
    """Mark the run's ``queued`` or ``started`` admission ``terminal``.

    Called from the ORM hook when a Run reaches a terminal status. Not fenced by epoch:
    rows left ``unknown`` by recovery are not matched, and a stale writer cannot revive them.
    """
    db.execute(update(SessionAdmissionRecord).where(
        SessionAdmissionRecord.run_id == run_id,
        SessionAdmissionRecord.status.in_(_RELEASING_STATUSES),
    ).values(status="terminal", updated_at=now))


def finish(db: Session, *, epoch: int, admission_id: UUID, now: datetime) -> None:
    """Mark a ``started`` admission ``terminal``. Only the claiming epoch may finish it.

    Raises ``StaleEpoch`` if the caller's epoch is not current or the row is no longer
    ``started`` under this epoch. Nothing is written in either case.
    """
    require_epoch(db, epoch)
    result = db.execute(update(SessionAdmissionRecord).where(
        SessionAdmissionRecord.admission_id == admission_id,
        SessionAdmissionRecord.status == "started",
        SessionAdmissionRecord.owner_epoch == epoch,
    ).values(status="terminal", updated_at=now))
    if result.rowcount != 1:
        raise StaleEpoch(f"admission {admission_id} is not started under epoch {epoch}")


def recover_previous_epochs(db: Session, *, epoch: int, now: datetime) -> list[UUID]:
    """Mark ``started`` admissions from older epochs as ``unknown``; return their run ids.

    Called once after ``begin_process``. Rows claimed by the current epoch are left alone.
    Nothing is replayed: the session stays blocked until ``resolve_unknown``.
    """
    require_epoch(db, epoch)
    rows = db.scalars(select(SessionAdmissionRecord).where(
        SessionAdmissionRecord.status == "started",
        SessionAdmissionRecord.owner_epoch != epoch,
    )).all()
    run_ids = [row.run_id for row in rows]
    for row in rows:
        row.status = "unknown"
        row.updated_at = now
    db.flush()
    return run_ids


def resolve_unknown(
    db: Session, *, epoch: int, admission_id: UUID, tenant_id: UUID, actor_id: UUID, now: datetime,
) -> None:
    """Explicitly clear an ``unknown`` admission so its session can run again.

    This is the only transition out of ``unknown``. It writes an audit record naming the
    actor, in the same transaction. Rejects rows that are not ``unknown``.
    """
    require_epoch(db, epoch)
    row = db.scalar(select(SessionAdmissionRecord).where(
        SessionAdmissionRecord.admission_id == admission_id,
    ))
    if row is None:
        raise AdmissionNotFound(str(admission_id))
    if row.status != "unknown":
        raise NotUnknown(f"admission {admission_id} is {row.status}, not unknown")
    row.status = "terminal"
    row.updated_at = now
    audit(db, tenant_id, actor_id, "run.unknown_resolved", "session_admission", str(admission_id),
          {"run_id": str(row.run_id), "session_id": str(row.session_id)})
    db.flush()


def install_run_terminal_hook() -> None:
    """Release admissions when a Run reaches a terminal status, for every ORM session.

    Terminal writes reach the database through several paths (repository, compatibility
    facade, lease and cancellation code). Hooking the flush covers all of them without
    touching each path. Idempotent: calling it twice registers one listener.
    """
    if event.contains(Session, "before_flush", _release_terminal_runs):
        return
    event.listen(Session, "before_flush", _release_terminal_runs)


def _release_terminal_runs(db: Session, _flush_context, _instances) -> None:
    now = utc_now()
    for obj in list(db.dirty):
        if not isinstance(obj, RunRecord):
            continue
        if RunStatus(obj.status).terminal:
            finish_run(db, run_id=obj.id, now=now)


__all__ = [
    "ADMISSION_QUEUE_MAX",
    "AdmissionNotFound",
    "AdmissionView",
    "NotUnknown",
    "cas_claim",
    "claim_run",
    "queue_position",
    "run_admission",
    "finish_run",
    "install_run_terminal_hook",
    "select_head",
    "LedgerError",
    "QueueFull",
    "StaleClaim",
    "StaleEpoch",
    "begin_process",
    "claim_next",
    "current_epoch",
    "enqueue",
    "finish",
    "recover_previous_epochs",
    "require_epoch",
    "resolve_unknown",
    "session_blocked",
]


# Importing this module (which submission and the worker both do) installs the terminal hook.
install_run_terminal_hook()
