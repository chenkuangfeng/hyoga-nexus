"""Who may read or change a knowledge base (openspec 2026-11-06-knowledge-base K1, design section 6).

- Read: an active member of the base's space, or an active member of a space the base is shared with through
  ``resource_grants`` (kind ``knowledge_base``, not revoked), or through a shared space the base is shared into
  (``knowledge_base_shares``; any effective level reads, see ``shared_spaces.kb_shares``).
- Write follows ownership (openspec 2026-11-11-enterprise-saas decision 2), always for an active member of the
  base's own space:

  - *manage* (settings, pin, shares, maintainers): the creator of a ``personal`` base; a holder of
    ``enterprise_kbs:manage`` for an ``enterprise`` base (owners and admins hold it by default);
  - *maintain content* (documents, chunks, FAQ, tags, folders, wiki, rebuilds): whoever may manage, plus the
    members listed in ``knowledge_base_maintainers`` of an enterprise base;
  - *govern* (delete, convert to enterprise): whoever may manage, plus the space's owners and admins, so they can
    act on a member's personal base without editing it.

Unknown, deleted or unreadable bases all raise the same ``NotFound``, so callers cannot probe for ids.
Every search path calls :func:`readable_bases` at the moment of the search, so revocation and deletion take
effect on the next call.
"""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus_platform.authz.permissions import effective_permissions
from nexus_platform.errors import Forbidden, NotFound
from nexus_platform.orgs.access import membership_is_active
from nexus_platform.persistence.models import (KnowledgeBaseMaintainerRecord, KnowledgeBaseRecord, MembershipRecord,
                                               ResourceGrantRecord)
from nexus_platform.shared_spaces import kb_shares
from nexus_platform.tenants.service import ADMIN_ROLES

KIND = 'knowledge_base'
PERSONAL = 'personal'
ENTERPRISE = 'enterprise'
OWNERSHIPS = frozenset({PERSONAL, ENTERPRISE})
MANAGE_ENTERPRISE_KBS = 'enterprise_kbs:manage'


def _membership(db: Session, tenant_id: UUID, user_id: UUID) -> MembershipRecord | None:
    row = db.get(MembershipRecord, (tenant_id, user_id))
    return row if membership_is_active(db, row) else None


def shared_into(db: Session, kb: KnowledgeBaseRecord, tenant_id: UUID) -> bool:
    """True when ``kb`` is shared into ``tenant_id`` by an unrevoked grant."""
    return db.scalar(select(ResourceGrantRecord.id).where(
        ResourceGrantRecord.source_tenant_id == kb.tenant_id,
        ResourceGrantRecord.target_tenant_id == tenant_id,
        ResourceGrantRecord.kind == KIND,
        ResourceGrantRecord.resource_id == str(kb.id),
        ResourceGrantRecord.revoked_at.is_(None))) is not None


def can_read(db: Session, kb: KnowledgeBaseRecord, tenant_id: UUID, user_id: UUID) -> bool:
    """Read access from the caller's current space ``tenant_id``: own bases, tenant grants, or a shared space."""
    if kb.status != 'active' or _membership(db, tenant_id, user_id) is None:
        return False
    return kb.tenant_id == tenant_id or shared_into(db, kb, tenant_id) or kb.id in kb_shares.shared_levels(
        db, tenant_id, user_id)


def can_manage(db: Session, kb: KnowledgeBaseRecord, user_id: UUID) -> bool:
    """Settings, pin, shares and maintainers of the base, according to its ownership."""
    if kb.status != 'active' or _membership(db, kb.tenant_id, user_id) is None:
        return False
    if kb.ownership == PERSONAL:
        return kb.created_by == user_id
    return effective_permissions(db, kb.tenant_id, user_id).allows_api(MANAGE_ENTERPRISE_KBS)


def is_maintainer(db: Session, kb: KnowledgeBaseRecord, user_id: UUID) -> bool:
    """True when the user is a designated maintainer of an enterprise base (membership is checked by callers)."""
    return kb.ownership == ENTERPRISE and db.get(KnowledgeBaseMaintainerRecord, (kb.id, user_id)) is not None


def can_maintain(db: Session, kb: KnowledgeBaseRecord, user_id: UUID) -> bool:
    """Documents, chunks, FAQ entries, tags, folders, wiki pages and rebuilds of the base."""
    if can_manage(db, kb, user_id):
        return True
    return (kb.status == 'active' and _membership(db, kb.tenant_id, user_id) is not None
            and is_maintainer(db, kb, user_id))


def can_govern(db: Session, kb: KnowledgeBaseRecord, user_id: UUID) -> bool:
    """Delete or convert the base: its managers, plus the space's owners and admins."""
    if can_manage(db, kb, user_id):
        return True
    membership = _membership(db, kb.tenant_id, user_id)
    return kb.status == 'active' and membership is not None and membership.role in ADMIN_ROLES


def readable_base(db: Session, kb_id: UUID, tenant_id: UUID, user_id: UUID) -> KnowledgeBaseRecord:
    kb = db.get(KnowledgeBaseRecord, kb_id)
    if kb is None or not can_read(db, kb, tenant_id, user_id):
        raise NotFound('Knowledge base not found')
    return kb


def _own_base(db: Session, kb_id: UUID, tenant_id: UUID, user_id: UUID, allowed, message: str
              ) -> KnowledgeBaseRecord:
    kb = readable_base(db, kb_id, tenant_id, user_id)
    if kb.tenant_id != tenant_id or not allowed(db, kb, user_id):
        raise Forbidden(message)
    return kb


def manageable_base(db: Session, kb_id: UUID, tenant_id: UUID, user_id: UUID) -> KnowledgeBaseRecord:
    """A base of the caller's current space whose settings the caller may change. Shared bases are read-only here."""
    return _own_base(db, kb_id, tenant_id, user_id, can_manage, 'You cannot change this knowledge base')


def maintainable_base(db: Session, kb_id: UUID, tenant_id: UUID, user_id: UUID) -> KnowledgeBaseRecord:
    """A base of the caller's current space whose content the caller may maintain."""
    return _own_base(db, kb_id, tenant_id, user_id, can_maintain, 'You cannot maintain this knowledge base')


def governable_base(db: Session, kb_id: UUID, tenant_id: UUID, user_id: UUID) -> KnowledgeBaseRecord:
    """A base of the caller's current space that the caller may delete or convert."""
    return _own_base(db, kb_id, tenant_id, user_id, can_govern, 'You cannot delete this knowledge base')


def readable_bases(db: Session, tenant_id: UUID, user_id: UUID, kb_ids: list[UUID] | None = None
                   ) -> list[KnowledgeBaseRecord]:
    """Active bases readable from ``tenant_id``: the space's own plus those shared into it (optionally a subset)."""
    if _membership(db, tenant_id, user_id) is None:
        return []
    shared_ids = select(ResourceGrantRecord.resource_id).where(
        ResourceGrantRecord.target_tenant_id == tenant_id, ResourceGrantRecord.kind == KIND,
        ResourceGrantRecord.revoked_at.is_(None))
    query = select(KnowledgeBaseRecord).where(KnowledgeBaseRecord.status == 'active')
    if kb_ids is not None:
        if not kb_ids:
            return []
        query = query.where(KnowledgeBaseRecord.id.in_(kb_ids))
    rows = db.scalars(query.order_by(KnowledgeBaseRecord.pinned.desc(), KnowledgeBaseRecord.pinned_at.desc(),
                                     KnowledgeBaseRecord.created_at)).all()
    shared = {UUID(value) for value in db.scalars(shared_ids).all() if _is_uuid(value)}
    via_space = set(kb_shares.shared_levels(db, tenant_id, user_id))
    return [kb for kb in rows if kb.tenant_id == tenant_id or kb.id in via_space
            or (kb.id in shared and shared_into(db, kb, tenant_id))]


def _is_uuid(value: str) -> bool:
    try:
        UUID(value)
    except ValueError:
        return False
    return True
