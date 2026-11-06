"""Knowledge base HTTP API (openspec 2026-11-06-knowledge-base).

K0: the capability catalog the web client uses to render every WeKnora knowledge feature as available or
planned. Later stages add the knowledge base, document, vector store and search endpoints here.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from nexus_api.dependencies.platform import get_database_session, get_principal
from nexus_core.platform import Principal
from nexus_knowledge import capabilities
from nexus_platform.identity.service import require_membership, resolve_user

router = APIRouter(prefix='/api/v1/tenants/{tenant_id}/knowledge', tags=['Knowledge'])


@router.get('/capabilities')
def list_capabilities(tenant_id: UUID, principal: Principal = Depends(get_principal),
                      db: Session = Depends(get_database_session)) -> dict[str, object]:
    """Every knowledge feature with ``status`` (available | planned), ``stage`` and ``verified``.

    Members of the space only; the catalog is the same for every space.
    """
    user = resolve_user(db, principal)
    require_membership(db, tenant_id, user.id)
    return {'groups': list(capabilities.GROUPS), 'items': capabilities.snapshot()}
