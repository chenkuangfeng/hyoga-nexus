"""Sharing an enterprise knowledge base with a shared space (openspec 2026-11-06-knowledge-base K1.9a).

Same rules as :mod:`nexus_platform.shared_spaces.agent_shares` (WeKnora ``kbshare.go``):

- The base's managers (openspec 2026-11-11-enterprise-saas decision 2) share it into a shared space at a level (viewer, editor, admin). The owning
  space must itself be a member of that shared space. Sharing again changes the level.
- Members of a member space reach the base through that space. Per person the effective level is
  ``min(share level, the member space's role in the shared space, the person's own cap)``.
- Any effective level lets the person **read and search** the base. Changing a shared base (documents, settings, shares)
  stays with the owning space, so ``editor`` and ``admin`` are recorded and shown but do not widen access yet.
- Managing shares stays with the owning space.
"""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus_core.platform import Principal, new_id, utc_now
from nexus_platform.authz.audit import audit
from nexus_platform.errors import Forbidden, NotFound
from nexus_platform.identity.service import require_membership, require_tenant, resolve_user
from nexus_platform.orgs.access import is_space_manager, membership_is_active
from nexus_platform.persistence.models import (
    KnowledgeBaseRecord,
    KnowledgeBaseShareRecord,
    MembershipRecord,
    SharedSpaceRecord,
    SharedSpaceTenantMemberRecord,
    TenantRecord,
)
from nexus_platform.shared_spaces.agent_shares import LEVEL_RANK, effective_level

KIND = 'knowledge_base'


def _live_shared(db: Session, shared_id: UUID) -> SharedSpaceRecord:
    shared = db.get(SharedSpaceRecord, shared_id)
    if shared is None or shared.deleted_at is not None:
        raise NotFound('Shared space not found')
    return shared


def _owned_base(db: Session, tenant_id: UUID, kb_id: UUID) -> KnowledgeBaseRecord:
    kb = db.get(KnowledgeBaseRecord, kb_id)
    if kb is None or kb.tenant_id != tenant_id or kb.status != 'active':
        raise NotFound('Knowledge base not found')
    return kb


def _require_share_actor(db: Session, principal: Principal, tenant_id: UUID, kb_id: UUID, *,
                         governance: bool) -> tuple[UUID, KnowledgeBaseRecord]:
    """Sharing needs management of the base (its creator, or ``enterprise_kbs:manage`` for an enterprise base);
    listing and removing shares (``governance=True``) is also open to the space's owners and admins."""
    from nexus_platform.knowledge.access import can_manage
    actor = resolve_user(db, principal)
    space = require_tenant(db, tenant_id)
    if space.kind != 'enterprise':
        raise NotFound('Knowledge base sharing is available in enterprise spaces only')
    require_membership(db, tenant_id, actor.id)
    kb = _owned_base(db, tenant_id, kb_id)
    if not (can_manage(db, kb, actor.id) or (governance and is_space_manager(db, tenant_id, actor.id))):
        raise Forbidden("Only the knowledge base's managers can share it")
    return actor.id, kb


def _view(share: KnowledgeBaseShareRecord, shared: SharedSpaceRecord, owner: TenantRecord) -> dict:
    return {'id': str(share.id), 'kb_id': str(share.kb_id), 'shared_space_id': str(shared.id),
            'shared_space_name': shared.name, 'level': share.level, 'created_at': share.created_at.isoformat(),
            'owner_tenant_id': str(owner.id), 'owner_tenant_name': owner.name}


def share_base(db: Session, principal: Principal, tenant_id: UUID, kb_id: UUID, shared_space_id: UUID,
               level: str) -> dict:
    """Share a base into a shared space, or change the level of an existing share."""
    if level not in LEVEL_RANK:
        raise ValueError('Level must be viewer, editor or admin')
    now = utc_now()
    with db.begin():
        actor_id, kb = _require_share_actor(db, principal, tenant_id, kb_id, governance=False)
        if kb.visibility != 'tenant':
            from nexus_platform.errors import InvalidConfiguration
            raise InvalidConfiguration('Only knowledge bases visible to the whole enterprise can be shared')
        shared = _live_shared(db, shared_space_id)
        from nexus_platform.tenants.policies import require_external_sharing
        require_external_sharing(db, tenant_id, shared.id)
        if db.get(SharedSpaceTenantMemberRecord, (shared.id, tenant_id)) is None:
            raise Forbidden('Your space must be a member of the shared space before sharing into it')
        share = db.scalar(select(KnowledgeBaseShareRecord).where(
            KnowledgeBaseShareRecord.kb_id == kb.id, KnowledgeBaseShareRecord.shared_space_id == shared.id))
        if share is None:
            share = KnowledgeBaseShareRecord(id=new_id(), tenant_id=tenant_id, kb_id=kb.id,
                                             shared_space_id=shared.id, level=level, created_by=actor_id,
                                             created_at=now, updated_at=now)
            db.add(share)
            action = 'knowledge_base.shared'
        elif share.level == level:
            action = ''
        else:
            share.level, share.updated_at = level, now
            action = 'knowledge_base.share_changed'
        db.flush()
        if action:
            audit(db, tenant_id, actor_id, action, KIND, str(kb.id), {'shared_space_id': str(shared.id), 'level': level})
        return _view(share, shared, db.get(TenantRecord, tenant_id))


def list_base_shares(db: Session, principal: Principal, tenant_id: UUID, kb_id: UUID) -> list[dict]:
    with db.begin():
        _require_share_actor(db, principal, tenant_id, kb_id, governance=True)
        owner = db.get(TenantRecord, tenant_id)
        rows = db.execute(
            select(KnowledgeBaseShareRecord, SharedSpaceRecord)
            .join(SharedSpaceRecord, SharedSpaceRecord.id == KnowledgeBaseShareRecord.shared_space_id)
            .where(KnowledgeBaseShareRecord.kb_id == kb_id, SharedSpaceRecord.deleted_at.is_(None))
            .order_by(KnowledgeBaseShareRecord.created_at)).all()
        return [_view(share, shared, owner) for share, shared in rows]


def unshare_base(db: Session, principal: Principal, tenant_id: UUID, kb_id: UUID, shared_space_id: UUID) -> None:
    with db.begin():
        actor_id, kb = _require_share_actor(db, principal, tenant_id, kb_id, governance=True)
        share = db.scalar(select(KnowledgeBaseShareRecord).where(
            KnowledgeBaseShareRecord.kb_id == kb.id, KnowledgeBaseShareRecord.shared_space_id == shared_space_id))
        if share is None:
            raise NotFound('This knowledge base is not shared with that shared space')
        db.delete(share)
        audit(db, tenant_id, actor_id, 'knowledge_base.unshared', KIND, str(kb.id),
              {'shared_space_id': str(shared_space_id)})


def shared_levels(db: Session, caller_tenant_id: UUID, user_id: UUID) -> dict[UUID, str]:
    """For each base shared into a shared space where the caller's space is a member: the best effective level.

    Returns an empty mapping when the person is not an active member of ``caller_tenant_id``. Does not open a
    transaction, so it can run inside the caller's.
    """
    membership = db.get(MembershipRecord, (caller_tenant_id, user_id))
    if not membership_is_active(db, membership):
        return {}
    rows = db.execute(
        select(KnowledgeBaseShareRecord, SharedSpaceTenantMemberRecord)
        .join(SharedSpaceTenantMemberRecord,
              SharedSpaceTenantMemberRecord.shared_space_id == KnowledgeBaseShareRecord.shared_space_id)
        .join(SharedSpaceRecord, SharedSpaceRecord.id == KnowledgeBaseShareRecord.shared_space_id)
        .where(SharedSpaceTenantMemberRecord.tenant_id == caller_tenant_id,
               SharedSpaceRecord.deleted_at.is_(None))).all()
    best: dict[UUID, str] = {}
    for share, member in rows:
        level = effective_level(share.level, member.role, membership.role)
        if level is not None and (share.kb_id not in best or LEVEL_RANK[level] > LEVEL_RANK[best[share.kb_id]]):
            best[share.kb_id] = level
    return best


__all__ = ['list_base_shares', 'share_base', 'shared_levels', 'unshare_base']
