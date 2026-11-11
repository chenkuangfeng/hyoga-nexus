"""Token usage reports and monthly limits (openspec 2026-11-11-enterprise-saas E6).

- ``GET /api/v1/tenants/{tenant_id}/admin/usage``: sums grouped by member, agent, model, day or department
  (``models:manage``).
- ``GET /api/v1/tenants/{tenant_id}/usage/me``: the caller's own sums.
- ``GET|PUT /api/v1/tenants/{tenant_id}/admin/usage/limits``: monthly limits of the enterprise, a department or a
  member (``models:manage``); ``monthly_tokens: null`` removes one.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from nexus_api.dependencies.platform import get_database_session, get_principal
from nexus_core.platform import Principal
from nexus_platform.usage import service

router = APIRouter(prefix='/api/v1/tenants/{tenant_id}', tags=['Usage'])
Group = Literal['user', 'agent', 'model', 'day', 'org_unit']


class LimitInput(BaseModel):
    scope_kind: Literal['tenant', 'org_unit', 'user']
    scope_id: UUID | None = None
    monthly_tokens: int | None = Field(default=None, gt=0)


@router.get('/admin/usage')
def enterprise_usage(tenant_id: UUID, group_by: Group = 'user', start: date | None = None, end: date | None = None,
                     principal: Principal = Depends(get_principal),
                     db: Session = Depends(get_database_session)) -> dict[str, Any]:
    return {'items': service.report(db, principal, tenant_id, group_by=group_by, start=start, end=end)}


@router.get('/usage/me')
def my_usage(tenant_id: UUID, group_by: Group = 'day', start: date | None = None, end: date | None = None,
             principal: Principal = Depends(get_principal),
             db: Session = Depends(get_database_session)) -> dict[str, Any]:
    return {'items': service.report(db, principal, tenant_id, group_by=group_by, start=start, end=end,
                                    only_self=True)}


@router.get('/admin/usage/limits')
def list_limits(tenant_id: UUID, principal: Principal = Depends(get_principal),
                db: Session = Depends(get_database_session)) -> dict[str, Any]:
    return {'items': service.list_limits(db, principal, tenant_id)}


@router.put('/admin/usage/limits')
def set_limit(tenant_id: UUID, body: LimitInput, principal: Principal = Depends(get_principal),
              db: Session = Depends(get_database_session)) -> dict[str, Any]:
    return {'limit': service.set_limit(db, principal, tenant_id, scope_kind=body.scope_kind, scope_id=body.scope_id,
                                       monthly_tokens=body.monthly_tokens)}
