"""Knowledge base maintainers and personal-to-enterprise conversion (openspec 2026-11-11-enterprise-saas, decision 2).

- Maintainers: an enterprise base's managers (``enterprise_kbs:manage``) name members who may maintain its content
  (documents, chunks, FAQ, tags, folders, wiki). Settings, visibility, deletion and sharing stay with the managers.
  Personal bases have no maintainers: only their creator maintains them.
- Conversion: an owner or admin turns a member's personal base into an enterprise base. The creator loses
  management; enterprise managers gain it. The creator may then be named a maintainer.

All functions run inside the caller's transaction and write audit records.
"""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus_core.platform import utc_now
from nexus_platform.authz.audit import audit
from nexus_platform.errors import Conflict, Forbidden, InvalidConfiguration, NotFound
from nexus_platform.knowledge import access
from nexus_platform.orgs.access import membership_is_active
from nexus_platform.persistence.models import (KnowledgeBaseMaintainerRecord, KnowledgeBaseRecord, MembershipRecord,
                                               UserRecord)


def _enterprise_base(db: Session, tenant_id: UUID, user_id: UUID, kb_id: UUID) -> KnowledgeBaseRecord:
    kb = access.manageable_base(db, kb_id, tenant_id, user_id)
    if kb.ownership != access.ENTERPRISE:
        raise InvalidConfiguration('Only enterprise knowledge bases have maintainers')
    return kb


def maintainer_views(db: Session, kb: KnowledgeBaseRecord) -> list[dict]:
    rows = db.execute(
        select(KnowledgeBaseMaintainerRecord, UserRecord)
        .join(UserRecord, UserRecord.id == KnowledgeBaseMaintainerRecord.user_id)
        .where(KnowledgeBaseMaintainerRecord.kb_id == kb.id)
        .order_by(KnowledgeBaseMaintainerRecord.granted_at)).all()
    return [{'user_id': str(row.user_id), 'display_name': user.display_name, 'email': user.email,
             'granted_by': str(row.granted_by), 'granted_at': row.granted_at.isoformat()} for row, user in rows]


def list_maintainers(db: Session, tenant_id: UUID, user_id: UUID, kb_id: UUID) -> list[dict]:
    """The maintainers of an enterprise base; visible to the base's managers."""
    return maintainer_views(db, _enterprise_base(db, tenant_id, user_id, kb_id))


def add_maintainer(db: Session, tenant_id: UUID, user_id: UUID, kb_id: UUID, member_id: UUID) -> list[dict]:
    """Name an active member of the enterprise as a maintainer. Adding an existing maintainer changes nothing."""
    kb = _enterprise_base(db, tenant_id, user_id, kb_id)
    if not membership_is_active(db, db.get(MembershipRecord, (tenant_id, member_id))):
        raise NotFound('Member not found')
    if db.get(KnowledgeBaseMaintainerRecord, (kb.id, member_id)) is None:
        db.add(KnowledgeBaseMaintainerRecord(kb_id=kb.id, user_id=member_id, tenant_id=tenant_id,
                                             granted_by=user_id, granted_at=utc_now()))
        db.flush()
        audit(db, tenant_id, user_id, 'knowledge_base.maintainer_added', access.KIND, str(kb.id),
              {'user_id': str(member_id)})
    return maintainer_views(db, kb)


def remove_maintainer(db: Session, tenant_id: UUID, user_id: UUID, kb_id: UUID, member_id: UUID) -> None:
    kb = _enterprise_base(db, tenant_id, user_id, kb_id)
    row = db.get(KnowledgeBaseMaintainerRecord, (kb.id, member_id))
    if row is None:
        raise NotFound('Maintainer not found')
    db.delete(row)
    audit(db, tenant_id, user_id, 'knowledge_base.maintainer_removed', access.KIND, str(kb.id),
          {'user_id': str(member_id)})


def convert_to_enterprise(db: Session, tenant_id: UUID, user_id: UUID, kb_id: UUID) -> KnowledgeBaseRecord:
    """Turn a personal base into an enterprise base. Only the space's owners and admins may do this."""
    from nexus_platform.tenants.service import ADMIN_ROLES
    kb = access.readable_base(db, kb_id, tenant_id, user_id)
    membership = db.get(MembershipRecord, (tenant_id, user_id))
    if kb.tenant_id != tenant_id or membership is None or membership.role not in ADMIN_ROLES:
        raise Forbidden('Only an enterprise owner or admin can convert a personal knowledge base')
    if kb.ownership == access.ENTERPRISE:
        raise Conflict('The knowledge base is already an enterprise knowledge base')
    kb.ownership = access.ENTERPRISE
    kb.updated_at = utc_now()
    audit(db, tenant_id, user_id, 'knowledge_base.converted_to_enterprise', access.KIND, str(kb.id),
          {'creator_id': str(kb.created_by)})
    return kb
