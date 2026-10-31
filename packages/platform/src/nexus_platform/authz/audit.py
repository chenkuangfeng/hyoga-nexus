"""Append-only audit records for authorization, approval and resource decisions."""
from __future__ import annotations

from uuid import UUID

from nexus_core.platform import new_id, utc_now
from nexus_platform.persistence.models import AuditRecord
from sqlalchemy.orm import Session


def audit(
    session: Session,
    tenant_id: UUID,
    actor_user_id: UUID,
    action: str,
    target_type: str,
    target_id: str,
    metadata: dict[str, object] | None = None,
    *, result: str = "success",
) -> None:
    session.add(
        AuditRecord(
            id=new_id(),
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            result=result,
            metadata_json=metadata or {},
            created_at=utc_now(),
        )
    )
