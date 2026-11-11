"""Enterprise policy (openspec 2026-11-11-enterprise-saas decision 4).

The policy only tightens what the platform already allows. A missing ``enterprise_policies`` row means
:data:`DEFAULTS`. Every check reads the row at the moment of the request, so a change applies to the next call.

Checks owned here:

- :func:`require_self_build` — creating a personal agent (``self_build_agents``: ``all``, ``org_units``, ``none``).
  Owners and admins are never limited; viewers never self-build.
- :func:`personal_models_allowed` — selecting or running a model whose provider belongs to a member.
- :func:`require_external_sharing` — sharing into a shared space that also holds other enterprises.

``personal_wecom_channels`` and ``personal_external_channels`` are stored here and enforced by IM channels.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus_core.platform import Principal, TenantRole, utc_now
from nexus_platform.authz.audit import audit
from nexus_platform.authz.permissions import require_api_permission
from nexus_platform.errors import Forbidden, InvalidConfiguration
from nexus_platform.identity.service import require_membership, require_tenant, resolve_user
from nexus_platform.persistence.models import (EnterprisePolicyRecord, OrgUnitRecord, SharedSpaceTenantMemberRecord,
                                               UserOrgUnitRecord)

SELF_BUILD = ("all", "org_units", "none")
WECOM_CHANNEL_MODES = ("review", "open", "disabled")
MANAGERS = {TenantRole.OWNER.value, TenantRole.ADMIN.value}


@dataclass(frozen=True)
class Policy:
    self_build_agents: str = "all"
    self_build_org_unit_ids: list[str] = field(default_factory=list)
    personal_models: bool = False
    external_sharing: bool = False
    personal_wecom_channels: str = "review"
    personal_external_channels: bool = True
    retention_days: int | None = None


DEFAULTS = Policy()
FIELDS = tuple(asdict(DEFAULTS))


def get_policy(db: Session, tenant_id: UUID) -> Policy:
    row = db.get(EnterprisePolicyRecord, tenant_id)
    if row is None:
        return DEFAULTS
    return Policy(**{name: getattr(row, name) for name in FIELDS})


def policy_view(policy: Policy) -> dict[str, Any]:
    return asdict(policy)


def read_policy(db: Session, principal: Principal, tenant_id: UUID) -> dict[str, Any]:
    """Every member may read the policy, so clients can hide what it forbids."""
    with db.begin():
        user = resolve_user(db, principal)
        require_tenant(db, tenant_id)
        require_membership(db, tenant_id, user.id)
        return policy_view(get_policy(db, tenant_id))


def _validate(changes: dict[str, Any], tenant_id: UUID, db: Session) -> dict[str, Any]:
    unknown = set(changes) - set(FIELDS)
    if unknown:
        raise InvalidConfiguration(f"Unknown policy field: {', '.join(sorted(unknown))}")
    clean = dict(changes)
    if "self_build_agents" in clean and clean["self_build_agents"] not in SELF_BUILD:
        raise InvalidConfiguration("self_build_agents must be all, org_units or none")
    if "personal_wecom_channels" in clean and clean["personal_wecom_channels"] not in WECOM_CHANNEL_MODES:
        raise InvalidConfiguration("personal_wecom_channels must be review, open or disabled")
    if "self_build_org_unit_ids" in clean:
        ids = [str(UUID(str(value))) for value in clean["self_build_org_unit_ids"] or []]
        known = {str(value) for value in db.scalars(select(OrgUnitRecord.id).where(
            OrgUnitRecord.tenant_id == tenant_id, OrgUnitRecord.id.in_([UUID(value) for value in ids])))}
        if set(ids) - known:
            raise InvalidConfiguration("self_build_org_unit_ids must name departments of this enterprise")
        clean["self_build_org_unit_ids"] = sorted(set(ids))
    if "retention_days" in clean and clean["retention_days"] is not None:
        days = int(clean["retention_days"])
        if days < 1 or days > 3650:
            raise InvalidConfiguration("retention_days must be between 1 and 3650")
        clean["retention_days"] = days
    for name in ("personal_models", "external_sharing", "personal_external_channels"):
        if name in clean:
            clean[name] = bool(clean[name])
    return clean


def update_policy(db: Session, principal: Principal, tenant_id: UUID, changes: dict[str, Any]) -> dict[str, Any]:
    """Change some policy fields. Needs ``policy:manage``; writes an audit record with the changed fields."""
    with db.begin():
        user = resolve_user(db, principal)
        require_tenant(db, tenant_id)
        require_membership(db, tenant_id, user.id)
        require_api_permission(db, tenant_id, user.id, "policy:manage")
        clean = _validate(changes, tenant_id, db)
        row = db.get(EnterprisePolicyRecord, tenant_id)
        if row is None:
            row = EnterprisePolicyRecord(tenant_id=tenant_id, **asdict(DEFAULTS))
            db.add(row)
        for name, value in clean.items():
            setattr(row, name, value)
        row.updated_by, row.updated_at = user.id, utc_now()
        db.flush()
        audit(db, tenant_id, user.id, "enterprise.policy_updated", "tenant", str(tenant_id),
              {"fields": sorted(clean)})
        return policy_view(get_policy(db, tenant_id))


def _units_with_ancestors(db: Session, tenant_id: UUID, user_id: UUID) -> set[str]:
    units = set(db.scalars(select(UserOrgUnitRecord.unit_id).where(
        UserOrgUnitRecord.tenant_id == tenant_id, UserOrgUnitRecord.user_id == user_id)))
    seen: set[UUID] = set()
    pending = list(units)
    while pending:  # walk up to the root; the tree is acyclic (orgs.service refuses cycles)
        unit_id = pending.pop()
        if unit_id in seen:
            continue
        seen.add(unit_id)
        unit = db.get(OrgUnitRecord, unit_id)
        if unit is not None and unit.parent_id is not None:
            pending.append(unit.parent_id)
    return {str(unit) for unit in seen}


def can_self_build(db: Session, tenant_id: UUID, user_id: UUID, role: str) -> bool:
    if role in MANAGERS:
        return True
    if role == TenantRole.VIEWER.value:
        return False
    policy = get_policy(db, tenant_id)
    if policy.self_build_agents == "all":
        return True
    if policy.self_build_agents == "none":
        return False
    return bool(_units_with_ancestors(db, tenant_id, user_id) & set(policy.self_build_org_unit_ids))


def require_self_build(db: Session, tenant_id: UUID, user_id: UUID) -> None:
    membership = require_membership(db, tenant_id, user_id)
    if not can_self_build(db, tenant_id, user_id, membership.role):
        raise Forbidden("Your enterprise does not allow you to create agents")


def personal_models_allowed(db: Session, tenant_id: UUID) -> bool:
    return get_policy(db, tenant_id).personal_models


def require_external_sharing(db: Session, tenant_id: UUID, shared_space_id: UUID) -> None:
    """Refuse a share into a shared space holding other enterprises unless the policy allows it."""
    others = db.scalar(select(SharedSpaceTenantMemberRecord.tenant_id).where(
        SharedSpaceTenantMemberRecord.shared_space_id == shared_space_id,
        SharedSpaceTenantMemberRecord.tenant_id != tenant_id).limit(1))
    if others is not None and not get_policy(db, tenant_id).external_sharing:
        raise Forbidden("Your enterprise does not allow sharing with other enterprises")
