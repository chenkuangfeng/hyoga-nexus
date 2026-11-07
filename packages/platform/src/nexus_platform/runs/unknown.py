"""Sessions blocked by an ``unknown`` Run, and how they are released (openspec 2026-11-07-worker-concurrency, B).

When a worker is lost, the Runs it was executing are not replayed: a tool may already have changed something
outside. Their sessions stay blocked (``unknown`` admissions) until the block is cleared. This module lists the
blocked sessions, clears one on request, and clears the ones nobody is waiting for: a scheduled task's session has
no person to ask whether to resend, and one that is provably free of side effects can be cleared when the operator
allows it. Nothing here re-runs anything.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus_core.deployment import CONFIG_RELATIVE_PATH, DeploymentConfigError, section
from nexus_core.platform import Principal, TenantRole, utc_now
from nexus_platform.errors import Conflict, NotFound
from nexus_platform.identity.service import require_membership, resolve_user
from nexus_platform.persistence.models import RunRecord, ToolInvocationRecord
from nexus_platform.persistence.models.ledger import SessionAdmissionRecord
from nexus_platform.persistence.models.schedule import CronJobRecord
from nexus_platform.persistence.unit_of_work import SqlAlchemyUnitOfWork
from . import session_ledger as ledger

#: Whether a tool changes anything outside the platform. None means the tool is not known.
SideEffects = Callable[[str], "bool | None"]
_ADMIN_ROLES = {TenantRole.OWNER.value, TenantRole.ADMIN.value}


def auto_resolve_safe_unknown(path: Path | None = None) -> bool:
    """``[platform].auto_resolve_safe_unknown``: clear blocks that provably left nothing half-done. Off by default."""
    value = section("platform", path).get("auto_resolve_safe_unknown", False)
    if not isinstance(value, bool):
        raise DeploymentConfigError(f"{CONFIG_RELATIVE_PATH.as_posix()} [platform].auto_resolve_safe_unknown must be true or false")
    return value


def is_safe(db: Session, run_id: UUID, side_effects: SideEffects | None) -> bool:
    """True only when no tool call of the Run is left unfinished and able to have changed something.

    A call still ``running`` when the worker was lost may or may not have taken effect. It is harmless only when its
    tool is known to have no side effects; a tool that is unknown to ``side_effects`` counts as having them, so doubt
    never clears a session.
    """
    if side_effects is None:
        return False
    pending = db.scalars(select(ToolInvocationRecord).where(
        ToolInvocationRecord.run_id == run_id, ToolInvocationRecord.status == "running"))
    return all(side_effects((call.input_summary or {}).get("tool_name", "")) is False for call in pending)


def _view(db: Session, admission: SessionAdmissionRecord, run: RunRecord, side_effects: SideEffects | None) -> dict:
    return {"admission_id": admission.admission_id, "session_id": admission.session_id, "run_id": run.id,
            "run_status": run.status, "interrupted_at": run.ended_at or admission.updated_at,
            "safe": is_safe(db, run.id, side_effects)}


def _actor(db: Session, principal: Principal, tenant_id: UUID):
    user = resolve_user(db, principal)
    membership = require_membership(db, tenant_id, user.id)
    return user, membership.role in _ADMIN_ROLES


def list_unknown(db: Session, principal: Principal, tenant_id: UUID, side_effects: SideEffects | None = None) -> list[dict]:
    """Blocked sessions of the tenant: all for an owner or admin, only one's own otherwise."""
    user, is_admin = _actor(db, principal, tenant_id)
    query = (select(SessionAdmissionRecord, RunRecord)
             .join(RunRecord, RunRecord.id == SessionAdmissionRecord.run_id)
             .where(SessionAdmissionRecord.status == "unknown", RunRecord.tenant_id == tenant_id)
             .order_by(SessionAdmissionRecord.seq))
    if not is_admin:
        query = query.where(RunRecord.principal_id == user.id)
    return [_view(db, admission, run, side_effects) for admission, run in db.execute(query)]


def blocked_by(db: Session, session_id: UUID, side_effects: SideEffects | None = None) -> dict | None:
    """The ``unknown`` admission holding a session, for the conversation view; None when it is not blocked."""
    row = db.execute(select(SessionAdmissionRecord, RunRecord).join(RunRecord, RunRecord.id == SessionAdmissionRecord.run_id)
                     .where(SessionAdmissionRecord.session_id == session_id, SessionAdmissionRecord.status == "unknown")
                     .order_by(SessionAdmissionRecord.seq).limit(1)).first()
    if row is None:
        return None
    admission, run = row
    return {"reason": "unknown", **_view(db, admission, run, side_effects)}


def resolve_unknown_run(db: Session, principal: Principal, tenant_id: UUID, run_id: UUID) -> dict:
    """Clear the block a Run left on its session. Idempotent: a block already cleared reports the same result.

    The Run's owner and the tenant's owners and admins may do it; for anyone else the Run does not exist. A Run
    whose session is not blocked is a conflict, so a mistaken id cannot look like a success.
    """
    if db.in_transaction():
        db.rollback()  # reads made before this call (sign-in, listing) leave a transaction the unit of work cannot nest in
    with SqlAlchemyUnitOfWork(db) as work:
        session = work.session
        user, is_admin = _actor(session, principal, tenant_id)
        run = session.get(RunRecord, run_id)
        if run is None or run.tenant_id != tenant_id or not (is_admin or run.principal_id == user.id):
            raise NotFound("Run not found")
        admission = session.scalar(select(SessionAdmissionRecord).where(SessionAdmissionRecord.run_id == run_id))
        if admission is None:
            raise Conflict("Run has no blocked session")
        status = admission.status
        if status == "unknown":
            ledger.resolve_unknown_admin(session, admission_id=admission.admission_id, tenant_id=tenant_id,
                                         actor_id=user.id, now=utc_now())
            status = "terminal"
        elif status != "terminal":
            raise Conflict("Run does not block its session")
        return {"admission_id": admission.admission_id, "session_id": admission.session_id, "run_id": run_id,
                "status": status}


def settle_unattended(db: Session, now: datetime | None = None) -> list[UUID]:
    """Clear blocks held by scheduled tasks' sessions: nobody is waiting on them, and nobody could say to resend.

    Called at start-up recovery right after the lost Runs were marked ``unknown``. Returns the cleared run ids.
    """
    now = now or utc_now()
    rows = db.execute(select(SessionAdmissionRecord, RunRecord)
                      .join(RunRecord, RunRecord.id == SessionAdmissionRecord.run_id)
                      .join(CronJobRecord, CronJobRecord.session_id == SessionAdmissionRecord.session_id)
                      .where(SessionAdmissionRecord.status == "unknown")).all()
    cleared = []
    for admission, run in rows:
        if ledger.resolve_unknown_admin(db, admission_id=admission.admission_id, tenant_id=run.tenant_id,
                                        actor_id=run.principal_id, now=now, by="system"):
            cleared.append(run.id)
    return cleared


def settle_safe(db: Session, side_effects: SideEffects | None, now: datetime | None = None) -> list[UUID]:
    """Clear blocks whose Run provably left nothing half-done (see ``is_safe``); off unless the operator enables it."""
    now = now or utc_now()
    rows = db.execute(select(SessionAdmissionRecord, RunRecord)
                      .join(RunRecord, RunRecord.id == SessionAdmissionRecord.run_id)
                      .where(SessionAdmissionRecord.status == "unknown")).all()
    cleared = []
    for admission, run in rows:
        if is_safe(db, run.id, side_effects) and ledger.resolve_unknown_admin(
                db, admission_id=admission.admission_id, tenant_id=run.tenant_id, actor_id=run.principal_id,
                now=now, by="system"):
            cleared.append(run.id)
    return cleared


def list_unknown_all(db: Session, side_effects: SideEffects | None = None) -> list[dict]:
    """Every blocked session of every tenant, for the operator's command line."""
    rows = db.execute(select(SessionAdmissionRecord, RunRecord)
                      .join(RunRecord, RunRecord.id == SessionAdmissionRecord.run_id)
                      .where(SessionAdmissionRecord.status == "unknown").order_by(SessionAdmissionRecord.seq)).all()
    return [{"tenant_id": run.tenant_id, **_view(db, admission, run, side_effects)} for admission, run in rows]


def resolve_unknown_operator(db: Session, run_id: UUID) -> bool:
    """Clear a Run's block from the command line (no tenant permission check: the operator has the database).

    The audit entry is attributed to the Run's owner and marked ``by: operator``. False when it was not blocked.
    """
    admission = db.scalar(select(SessionAdmissionRecord).where(SessionAdmissionRecord.run_id == run_id))
    run = db.get(RunRecord, run_id)
    if admission is None or run is None:
        raise NotFound("Run not found")
    cleared = ledger.resolve_unknown_admin(db, admission_id=admission.admission_id, tenant_id=run.tenant_id,
                                           actor_id=run.principal_id, now=utc_now(), by="operator")
    db.commit()
    return cleared
