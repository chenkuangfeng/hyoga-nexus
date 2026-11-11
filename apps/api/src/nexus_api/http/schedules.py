"""Scheduled task endpoints (openspec 2026-11-07-tool-expansion 8.2a, task 10.2).

Members manage their own tasks; a space owner or admin can also list everyone's tasks and pause them. The rules,
limits and prompt screening live in `nexus_platform.schedule.service` and are the same ones the `cronjob_*` tools
use. `ScheduleError` is turned into the usual `{"error": {...}}` body by the handler in `main.py`.
"""
from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from nexus_core.platform import Principal
from nexus_platform.schedule import service
from nexus_api.dependencies.platform import get_database_session, get_principal

router = APIRouter(prefix='/api/v1/tenants/{tenant_id}/schedules', tags=['Schedules'])


class ScheduleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    prompt: str = Field(min_length=1, max_length=service.MAX_PROMPT_CHARS)
    agent_id: UUID
    schedule: dict[str, Any]
    timezone: str = Field(default='UTC', max_length=64)


class ScheduleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    prompt: str | None = Field(default=None, min_length=1, max_length=service.MAX_PROMPT_CHARS)
    schedule: dict[str, Any] | None = None
    timezone: str | None = Field(default=None, max_length=64)


class SchedulePreview(BaseModel):
    schedule: dict[str, Any]
    timezone: str = Field(default='UTC', max_length=64)
    count: int = Field(default=3, ge=1, le=service.PREVIEW_MAX)


@router.get('')
def list_schedules(tenant_id: UUID, scope: Literal['mine', 'all'] = Query('mine'),
                   principal: Principal = Depends(get_principal), db: Session = Depends(get_database_session)) -> dict[str, Any]:
    """The caller's tasks, or with ``scope=all`` everyone's (space owners and admins only)."""
    return {'items': service.list_jobs_detailed(db, principal, tenant_id, scope)}


@router.post('', status_code=201)
def create_schedule(tenant_id: UUID, body: ScheduleCreate, principal: Principal = Depends(get_principal),
                    db: Session = Depends(get_database_session)) -> dict[str, Any]:
    """Create a task on the agent's current published version."""
    return service.create_job_for_agent(db, principal, tenant_id, agent_id=body.agent_id, name=body.name,
                                        prompt=body.prompt, rule=body.schedule, timezone_name=body.timezone)


@router.post('/preview')
def preview_schedule(tenant_id: UUID, body: SchedulePreview, principal: Principal = Depends(get_principal),
                     db: Session = Depends(get_database_session)) -> dict[str, Any]:
    """The next fire times of a rule. Nothing is stored; any space member may ask."""
    service.list_jobs(db, principal, tenant_id)  # membership check only
    return {'times': service.preview(body.schedule, body.timezone, body.count)}


@router.get('/{job_id}')
def get_schedule(tenant_id: UUID, job_id: str, principal: Principal = Depends(get_principal),
                 db: Session = Depends(get_database_session)) -> dict[str, Any]:
    return service.get_job(db, principal, tenant_id, job_id)


@router.patch('/{job_id}')
def update_schedule(tenant_id: UUID, job_id: str, body: ScheduleUpdate, principal: Principal = Depends(get_principal),
                    db: Session = Depends(get_database_session)) -> dict[str, Any]:
    return service.update_job(db, principal, tenant_id, job_id, name=body.name, prompt=body.prompt, rule=body.schedule,
                              timezone_name=body.timezone)


@router.post('/{job_id}/pause')
def pause_schedule(tenant_id: UUID, job_id: str, principal: Principal = Depends(get_principal),
                   db: Session = Depends(get_database_session)) -> dict[str, Any]:
    return service.change_state(db, principal, tenant_id, job_id, 'pause')


@router.post('/{job_id}/resume')
def resume_schedule(tenant_id: UUID, job_id: str, principal: Principal = Depends(get_principal),
                    db: Session = Depends(get_database_session)) -> dict[str, Any]:
    return service.change_state(db, principal, tenant_id, job_id, 'resume')


@router.delete('/{job_id}', status_code=204)
def delete_schedule(tenant_id: UUID, job_id: str, principal: Principal = Depends(get_principal),
                    db: Session = Depends(get_database_session)) -> Response:
    service.change_state(db, principal, tenant_id, job_id, 'delete')
    return Response(status_code=204)


@router.post('/{job_id}/run', status_code=202)
def run_schedule_now(tenant_id: UUID, job_id: str, principal: Principal = Depends(get_principal),
                     db: Session = Depends(get_database_session)) -> dict[str, Any]:
    """Start one run now; the schedule is unchanged."""
    return service.run_now(db, principal, tenant_id, job_id)


@router.get('/{job_id}/runs')
def list_schedule_runs(tenant_id: UUID, job_id: str, limit: int = Query(20, ge=1, le=service.RUNS_MAX),
                       principal: Principal = Depends(get_principal),
                       db: Session = Depends(get_database_session)) -> dict[str, Any]:
    return {'items': service.list_runs(db, principal, tenant_id, job_id, limit)}
