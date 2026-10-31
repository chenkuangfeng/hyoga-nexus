"""Run audit adapter shares the business transaction and the existing audit writer."""
from typing import Any
from uuid import UUID
from sqlalchemy.orm import Session
from nexus_platform.authz.audit import audit


class SqlAlchemyRunAuditRepository:
    """Append an audit record without committing or opening another database session."""
    def __init__(self, session: Session):
        self.session = session

    def write(self, tenant_id: UUID, user_id: UUID, action: str,
              resource_type: str, resource_id: str, details: dict[str, Any] | None = None) -> None:
        audit(self.session, tenant_id, user_id, action, resource_type, resource_id, details)
