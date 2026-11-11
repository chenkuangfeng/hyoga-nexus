"""Department and member audiences (openspec 2026-11-11-enterprise-saas E5, decision 5; design section 8).

Matching uses the organization at the time of the check:

- a ``user`` row matches that member;
- an ``org_unit`` row matches members placed in that department, and, with ``include_descendants``, members of any
  department below it. The member's departments and all their ancestors are computed once per call.

Agent audiences grant use (``view`` and ``run``). Knowledge base audiences grant reading of ``scoped`` bases.
Writers need maintenance of the agent, or management of the base; every principal must belong to the enterprise.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus_core.platform import new_id, utc_now
from nexus_platform.authz.audit import audit
from nexus_platform.errors import InvalidConfiguration, NotFound
from nexus_platform.orgs.access import membership_is_active
from nexus_platform.persistence.models import (AgentAudienceRecord, KnowledgeBaseAudienceRecord, MembershipRecord,
                                               OrgUnitRecord, UserOrgUnitRecord)

KINDS = ('user', 'org_unit')


@dataclass(frozen=True)
class Placement:
    """A member's departments, and those departments with all their ancestors."""
    direct: frozenset[UUID]
    with_ancestors: frozenset[UUID]


def placement(db: Session, tenant_id: UUID, user_id: UUID) -> Placement:
    direct = set(db.scalars(select(UserOrgUnitRecord.unit_id).where(
        UserOrgUnitRecord.tenant_id == tenant_id, UserOrgUnitRecord.user_id == user_id)))
    seen: set[UUID] = set()
    pending = list(direct)
    while pending:
        unit_id = pending.pop()
        if unit_id in seen:
            continue
        seen.add(unit_id)
        unit = db.get(OrgUnitRecord, unit_id)
        if unit is not None and unit.status == 'active' and unit.parent_id is not None:
            pending.append(unit.parent_id)
    return Placement(frozenset(direct), frozenset(seen))


def matches(row, user_id: UUID, where: Placement) -> bool:
    if row.principal_kind == 'user':
        return row.principal_id == user_id
    return row.principal_id in (where.with_ancestors if row.include_descendants else where.direct)


def in_agent_audience(db: Session, tenant_id: UUID, user_id: UUID, agent_id: UUID) -> bool:
    rows = db.scalars(select(AgentAudienceRecord).where(AgentAudienceRecord.agent_id == agent_id)).all()
    if not rows:
        return False
    where = placement(db, tenant_id, user_id)
    return any(matches(row, user_id, where) for row in rows)


def agents_for(db: Session, tenant_id: UUID, user_id: UUID) -> set[UUID]:
    """Agents of the enterprise whose audience includes the member."""
    where = placement(db, tenant_id, user_id)
    rows = db.scalars(select(AgentAudienceRecord).where(AgentAudienceRecord.tenant_id == tenant_id)).all()
    return {row.agent_id for row in rows if matches(row, user_id, where)}


def in_base_audience(db: Session, tenant_id: UUID, user_id: UUID, kb_id: UUID) -> bool:
    rows = db.scalars(select(KnowledgeBaseAudienceRecord).where(KnowledgeBaseAudienceRecord.kb_id == kb_id)).all()
    if not rows:
        return False
    where = placement(db, tenant_id, user_id)
    return any(matches(row, user_id, where) for row in rows)


def _validate(db: Session, tenant_id: UUID, items: Iterable[dict[str, Any]]) -> list[tuple[str, UUID, bool]]:
    clean: dict[tuple[str, UUID], bool] = {}
    for item in items:
        kind, principal_id = item.get('kind'), UUID(str(item.get('id')))
        if kind not in KINDS:
            raise InvalidConfiguration('Audience kind must be user or org_unit')
        if kind == 'user':
            if not membership_is_active(db, db.get(MembershipRecord, (tenant_id, principal_id))):
                raise NotFound('Member not found')
        else:
            unit = db.get(OrgUnitRecord, principal_id)
            if unit is None or unit.tenant_id != tenant_id:
                raise NotFound('Department not found')
        clean[(kind, principal_id)] = bool(item.get('include_descendants', True))
    return [(kind, principal_id, descendants) for (kind, principal_id), descendants in clean.items()]


def audience_view(rows) -> list[dict[str, Any]]:
    return [{'kind': row.principal_kind, 'id': str(row.principal_id), 'include_descendants': row.include_descendants}
            for row in rows]


def replace(db: Session, model, owner_column: str, owner_id: UUID, tenant_id: UUID, actor_id: UUID,
            items: Iterable[dict[str, Any]], *, action: str, target_type: str) -> list[dict[str, Any]]:
    """Replace one agent's or base's audience inside the caller's transaction and audit it."""
    clean = _validate(db, tenant_id, items)
    db.query(model).filter(getattr(model, owner_column) == owner_id).delete()
    db.flush()
    now = utc_now()
    for kind, principal_id, descendants in clean:
        db.add(model(id=new_id(), tenant_id=tenant_id, **{owner_column: owner_id}, principal_kind=kind,
                     principal_id=principal_id, include_descendants=descendants, granted_by=actor_id, created_at=now))
    db.flush()
    audit(db, tenant_id, actor_id, action, target_type, str(owner_id),
          {'audience': [{'kind': kind, 'id': str(pid), 'include_descendants': d} for kind, pid, d in clean]})
    return audience_view(db.scalars(select(model).where(getattr(model, owner_column) == owner_id)).all())


def covered_by(db: Session, tenant_id: UUID, agent_rows, base_rows) -> bool:
    """Whether every member an agent audience can reach is also in a base audience (used for bindings).

    Conservative: a member row is covered when the base names that member or one of their departments (with
    descendants as needed); a department row is covered when the base names that department, or an ancestor with
    descendants, and the base row reaches at least as deep.
    """
    for row in agent_rows:
        if row.principal_kind == 'user':
            where = placement(db, tenant_id, row.principal_id)
            if not any(matches(base, row.principal_id, where) for base in base_rows):
                return False
            continue
        unit_chain = placement_of_unit(db, row.principal_id)
        ok = False
        for base in base_rows:
            if base.principal_kind != 'org_unit':
                continue
            if base.principal_id == row.principal_id and (base.include_descendants or not row.include_descendants):
                ok = True
            elif base.include_descendants and base.principal_id in unit_chain:
                ok = True
        if not ok:
            return False
    return True


def placement_of_unit(db: Session, unit_id: UUID) -> set[UUID]:
    chain: set[UUID] = set()
    current = db.get(OrgUnitRecord, unit_id)
    while current is not None and current.id not in chain:
        chain.add(current.id)
        current = db.get(OrgUnitRecord, current.parent_id) if current.parent_id else None
    return chain
