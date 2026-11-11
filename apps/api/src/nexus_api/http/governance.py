"""Audit export (openspec 2026-11-11-enterprise-saas E7).

``GET /api/v1/tenants/{tenant_id}/admin/audit/export?start=YYYY-MM-DD&end=YYYY-MM-DD`` returns the audit records of
those whole days (UTC) as hash-chained JSON lines (``application/x-ndjson``); needs ``audit:read``. Retention runs
in the worker.
"""
from __future__ import annotations

from datetime import date, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from nexus_api.dependencies.platform import get_database_session, get_principal
from nexus_core.platform import Principal, utc_now
from nexus_platform.errors import InvalidConfiguration
from nexus_platform.governance import retention

router = APIRouter(prefix='/api/v1/tenants/{tenant_id}/admin', tags=['Governance'])


@router.get('/audit/export')
def export_audit(tenant_id: UUID, start: date | None = None, end: date | None = None,
                 principal: Principal = Depends(get_principal), db: Session = Depends(get_database_session)):
    end = end or utc_now().date()
    start = start or end - timedelta(days=30)
    if start > end or (end - start).days > 366:
        raise InvalidConfiguration('Export at most one year at a time, with start not after end')
    begin, finish = retention.day_bounds(start, end)
    lines = list(retention.export_lines(db, principal, tenant_id, start=begin, end=finish))
    filename = f'audit-{tenant_id}-{start}-{end}.jsonl'
    return StreamingResponse(iter(lines), media_type='application/x-ndjson',
                             headers={'Content-Disposition': f'attachment; filename="{filename}"'})
