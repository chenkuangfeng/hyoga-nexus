"""Memory consolidation passes (openspec 2026-11-06-memory-evolution stage 3, C2).

The worker calls `consolidation_tick` while idle. A pass reviews one owner's live entries, asks the
owner's capture model whether each candidate cluster says one thing several ways, and records a merge
draft for every confirmed cluster (`nexus_memory.service.propose_merge`). Nothing is published or
archived until the owner reviews the draft.

When a pass runs:
- background: the owner enabled automatic capture with a model, memory allows capture
  (`write_mode='auto'`), the last pass is at least a day old, and the store has enough entries;
- requested: the owner asked through `request_consolidation` (at most once a minute) and a capture model
  is saved; this works even when automatic capture is off (decision 7) or the space is `explicit`.

Model calls run outside any transaction. A row in `memory_consolidation_state` leases the owner to one
worker; an expired lease is taken over.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Callable, Protocol
from uuid import UUID

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from nexus_core.platform import Principal, utc_now
from nexus_memory import consolidate as rules
from nexus_memory import service as memory_rules
from nexus_platform.authz.audit import audit
from nexus_platform.errors import Conflict, PlatformError
from nexus_platform.models.provider_settings import authorize_model, context
from nexus_platform.persistence.models import (
    AgentVersionRecord, MemoryCaptureSettingsRecord, MemoryConsolidationStateRecord, RunRecord,
)

from .repository import SqlMemoryRepository
from .switches import memory_state

logger = logging.getLogger(__name__)

#: How long a worker holds an owner while it runs the pass.
LEASE = timedelta(minutes=10)


class Merger(Protocol):
    """Model-backed merge check. Receives the cluster as `[{index, kind, title, content}]` and returns the
    raw answer (`{"merged": str, "keep": int}`, or an empty `merged` when the notes differ). No tools."""

    def __call__(self, *, entries: list[dict[str, Any]], model_version_id: UUID, tenant_id: UUID,
                 owner_id: UUID) -> Any: ...


def request_consolidation(db: Session, principal: Principal, tenant_id: UUID) -> dict[str, Any]:
    """Queue a requested pass for the caller. 409 when memory is off, no capture model is saved, or the
    previous request was less than a minute ago."""
    with db.begin():
        user, _ = context(db, principal, tenant_id)
        now = utc_now()
        if not memory_state(db, tenant_id=tenant_id, owner_id=user.id).available:
            raise Conflict('memory_disabled')
        model_version_id = _capture_model_for_owner(db, tenant_id, user.id)
        if model_version_id is None:
            raise Conflict('capture_model_required')
        try:
            authorize_model(db, tenant_id, user.id, model_version_id)
        except PlatformError:
            raise Conflict('capture_model_required') from None
        state = _state(db, tenant_id, user.id, lock=True)
        if state.last_forced_at is not None and _aware(state.last_forced_at) > now - rules.FORCED_INTERVAL:
            raise Conflict('too_soon')
        state.requested_at = state.last_forced_at = now
        audit(db, tenant_id, user.id, 'memory.consolidation_requested', 'memory', '', {})
        return {'status': 'queued'}


@dataclass(frozen=True)
class _Due:
    tenant_id: UUID
    owner_id: UUID
    forced: bool


def claim_due(db: Session, *, worker_id: str, now: datetime | None = None) -> _Due | None:
    """Lease the next owner whose pass is due: requested passes first, then daily background passes."""
    now = now or utc_now()
    free = or_(MemoryConsolidationStateRecord.lease_until.is_(None), MemoryConsolidationStateRecord.lease_until < now)
    requested = db.execute(select(MemoryConsolidationStateRecord.tenant_id, MemoryConsolidationStateRecord.owner_user_id)
                           .where(MemoryConsolidationStateRecord.requested_at.is_not(None), free).limit(1)).first()
    candidates: list[_Due] = [_Due(requested[0], requested[1], True)] if requested else []
    if not candidates:
        stale = now - rules.BACKGROUND_INTERVAL
        rows = db.execute(
            select(MemoryCaptureSettingsRecord.tenant_id, MemoryCaptureSettingsRecord.owner_user_id)
            .outerjoin(MemoryConsolidationStateRecord,
                       (MemoryConsolidationStateRecord.tenant_id == MemoryCaptureSettingsRecord.tenant_id)
                       & (MemoryConsolidationStateRecord.owner_user_id == MemoryCaptureSettingsRecord.owner_user_id))
            .where(MemoryCaptureSettingsRecord.enabled.is_(True),
                   MemoryCaptureSettingsRecord.model_profile_version_id.is_not(None),
                   or_(MemoryConsolidationStateRecord.tenant_id.is_(None),
                       (or_(MemoryConsolidationStateRecord.last_run_at.is_(None),
                            MemoryConsolidationStateRecord.last_run_at < stale)) & free))
            .limit(20)).all()
        candidates = [_Due(tenant, owner, False) for tenant, owner in rows]
        # Agent-owned capture settings live in immutable Run snapshots rather than the
        # legacy per-member table. Recent completed Runs provide the owner candidates;
        # deduplicate below and let `_capture_policy_for_owner` select the newest enabled Agent.
        recent_runs = db.scalars(select(RunRecord).where(
            RunRecord.status == 'completed').order_by(RunRecord.ended_at.desc()).limit(500)).all()
        seen = {(item.tenant_id, item.owner_id) for item in candidates}
        for run in recent_runs:
            if len(candidates) >= 20:
                break
            key = (run.tenant_id, run.principal_id)
            if key in seen:
                continue
            state = db.get(MemoryConsolidationStateRecord, key)
            if state and state.last_run_at and _aware(state.last_run_at) >= now - rules.BACKGROUND_INTERVAL:
                continue
            if state and state.lease_until and _aware(state.lease_until) >= now:
                continue
            enabled, model_id = _capture_policy_for_owner(db, run.tenant_id, run.principal_id)
            if enabled and model_id and memory_state(db, tenant_id=run.tenant_id,
                                                     owner_id=run.principal_id).capture_allowed:
                candidates.append(_Due(run.tenant_id, run.principal_id, False))
                seen.add(key)
    for due in candidates:
        _state(db, due.tenant_id, due.owner_id)
        won = db.execute(update(MemoryConsolidationStateRecord).where(
            MemoryConsolidationStateRecord.tenant_id == due.tenant_id,
            MemoryConsolidationStateRecord.owner_user_id == due.owner_id,
            or_(MemoryConsolidationStateRecord.lease_until.is_(None), MemoryConsolidationStateRecord.lease_until < now))
            .values(lease_owner=worker_id, lease_until=now + LEASE)).rowcount
        if won:
            return due
    return None


def run_pass(factory: Callable[[], Session], due: _Due, merger: Merger, *, now: datetime | None = None) -> dict[str, int]:
    """Review one leased owner and record merge drafts; always releases the lease and stamps the run."""
    now = now or utc_now()
    stats = {'clusters': 0, 'calls': 0, 'drafts': 0, 'failed': 0}
    try:
        with factory() as db, db.begin():
            plan = _plan(db, due)
        if plan is None:
            return stats
        clusters, version_id = plan
        stats['clusters'] = len(clusters)
        for cluster in clusters:
            members = [{'index': index, 'kind': item.entry.kind, 'title': item.entry.title, 'content': item.content}
                       for index, item in enumerate(cluster.entries)]
            try:
                raw = merger(entries=members, model_version_id=version_id, tenant_id=due.tenant_id,
                             owner_id=due.owner_id)
            except PlatformError:
                break  # the model or key stopped being usable: end the pass, try again next time
            except Exception:  # a provider error must not keep the owner leased; count it and go on
                logger.warning('memory consolidation call failed', extra={'tenant_id': str(due.tenant_id)})
                stats['failed'] += 1
                continue
            stats['calls'] += 1
            decision = rules.validate_merge(raw, len(cluster.entries))
            if decision is None:
                continue
            keep = cluster.entries[decision.keep]
            others = [item for index, item in enumerate(cluster.entries) if index != decision.keep]
            with factory() as db, db.begin():
                outcome = memory_rules.propose_merge(SqlMemoryRepository(db), due.tenant_id, due.owner_id,
                                                     keep=keep, others=others, merged=decision.merged)
            stats['drafts'] += outcome['status'] == 'pending'
        return stats
    finally:
        with factory() as db, db.begin():
            state = _state(db, due.tenant_id, due.owner_id, lock=True)
            state.last_run_at = now
            if due.forced:
                state.requested_at = None
            state.lease_owner = state.lease_until = None
            audit(db, due.tenant_id, due.owner_id, 'memory.consolidation', 'memory', '',
                  {'forced': due.forced, **stats})


def consolidation_tick(factory: Callable[[], Session], merger: Merger, *, worker_id: str,
                       now: datetime | None = None) -> bool:
    """Run one due pass if there is one. Returns True when an owner was processed."""
    now = now or utc_now()
    with factory() as db, db.begin():
        due = claim_due(db, worker_id=worker_id, now=now)
    if due is None:
        return False
    run_pass(factory, due, merger, now=now)
    return True


def _plan(db: Session, due: _Due) -> tuple[list[rules.Cluster], UUID] | None:
    """Clusters to check and the model to check them with, or None when this pass makes no model call."""
    settings = db.get(MemoryCaptureSettingsRecord, (due.tenant_id, due.owner_id))
    if due.forced:
        version_id = _capture_model_for_owner(db, due.tenant_id, due.owner_id)
    else:
        capture_enabled, version_id = _capture_policy_for_owner(db, due.tenant_id, due.owner_id)
        if not capture_enabled:
            return None
    if version_id is None:
        return None
    state = memory_state(db, tenant_id=due.tenant_id, owner_id=due.owner_id)
    if not state.available or (not due.forced and not state.capture_allowed):
        return None
    try:
        authorize_model(db, due.tenant_id, due.owner_id, version_id)
    except PlatformError:
        return None
    repo = SqlMemoryRepository(db)
    entries = [item for item in repo.live_entries(due.tenant_id, due.owner_id) if item.entry.enabled]
    if len(entries) < rules.MIN_ENTRIES:
        return None
    exclude = memory_rules.merge_targets(repo, due.tenant_id, due.owner_id)
    found = rules.clusters(entries, overlap=rules.FORCED_OVERLAP if due.forced else rules.BACKGROUND_OVERLAP,
                           max_clusters=rules.FORCED_CLUSTERS if due.forced else rules.BACKGROUND_CLUSTERS,
                           exclude=exclude)
    return (found, version_id) if found else None


def _capture_model_for_owner(db: Session, tenant_id: UUID, owner_id: UUID) -> UUID | None:
    """Resolve a configured Agent model, with legacy member settings as fallback."""
    return _capture_policy_for_owner(db, tenant_id, owner_id, allow_disabled=True)[1]


def _capture_policy_for_owner(db: Session, tenant_id: UUID, owner_id: UUID, *,
                              allow_disabled: bool = False) -> tuple[bool, UUID | None]:
    """Return the newest Agent capture policy, falling back to the legacy member setting."""
    runs = db.scalars(select(RunRecord).where(
        RunRecord.tenant_id == tenant_id, RunRecord.principal_id == owner_id,
        RunRecord.status == 'completed').order_by(RunRecord.ended_at.desc()).limit(100)).all()
    version_ids: set[UUID] = set()
    for run in runs:
        raw = (run.config_snapshot or {}).get('agent_version_id')
        try:
            if raw:
                version_ids.add(UUID(str(raw)))
        except ValueError:
            continue
    versions = (db.scalars(select(AgentVersionRecord).where(AgentVersionRecord.id.in_(version_ids))).all()
                if version_ids else [])
    by_id = {version.id: version for version in versions}
    has_agent_policy = False
    for run in runs:
        snapshot = run.config_snapshot or {}
        try:
            version_id = UUID(str(snapshot['agent_version_id']))
        except (KeyError, TypeError, ValueError):
            continue
        version = by_id.get(version_id)
        budgets = version.budgets if version else {}
        memory = budgets.get('memory') if isinstance(budgets, dict) else None
        if not isinstance(memory, dict) or not isinstance(memory.get('capture_enabled'), bool):
            continue
        has_agent_policy = True
        selected = memory.get('capture_model_version_id') or snapshot.get('model_profile_version_id')
        if not memory['capture_enabled']:
            if allow_disabled and selected:
                try:
                    return False, UUID(str(selected))
                except ValueError:
                    continue
            continue
        if selected:
            try:
                return True, UUID(str(selected))
            except ValueError:
                continue
    if has_agent_policy:
        return False, None
    settings = db.get(MemoryCaptureSettingsRecord, (tenant_id, owner_id))
    return (bool(settings and settings.enabled), settings.model_profile_version_id if settings else None)


def _state(db: Session, tenant_id: UUID, owner_id: UUID, *, lock: bool = False) -> MemoryConsolidationStateRecord:
    row = db.get(MemoryConsolidationStateRecord, (tenant_id, owner_id), with_for_update=lock)
    if row is None:
        row = MemoryConsolidationStateRecord(tenant_id=tenant_id, owner_user_id=owner_id)
        db.add(row)
        db.flush()
    return row


def _aware(value: datetime) -> datetime:
    from datetime import timezone
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
