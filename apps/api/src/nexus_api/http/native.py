"""Native user preferences, owned memory publication and durable runtime corrections."""
from typing import Any
from uuid import UUID
from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from nexus_core.platform import Principal
from nexus_api.dependencies.platform import get_principal, get_database_session
from nexus_platform.runs import settings, directives
from nexus_platform.memory import service as memory

router = APIRouter(prefix='/api/v1/tenants/{tenant_id}/native', tags=['Native settings'])


class PreferencesInput(BaseModel):
    """Versioned, typed-at-service configuration; arbitrary secret options are not accepted."""
    settings: dict[str, Any]
    expected_version: int = Field(ge=0)


class SteerInput(BaseModel):
    """A correction from the Run owner; not a second concurrent Run."""
    content: str = Field(min_length=1, max_length=8000)


class MemoryReview(BaseModel):
    """An explicit human publication decision, bound to a previously recorded model draft."""
    approve: bool
    title: str = Field(default='', max_length=160)
    project: str = Field(default='', max_length=160)
    entry_id: UUID | None = None
    expected_version: int = Field(default=0, ge=0)


class MemoryRestore(BaseModel):
    """Restore a historical version without overwriting newer history."""
    version: int = Field(ge=1)
    expected_version: int = Field(ge=1)


@router.get('/settings')
def get_settings(tenant_id: UUID, principal: Principal = Depends(get_principal), db: Session = Depends(get_database_session)):
    """Return current personal behavior/budget settings and form metadata."""
    return settings.load(db, principal, tenant_id)


@router.put('/settings')
def save_settings(tenant_id: UUID, body: PreferencesInput, principal: Principal = Depends(get_principal), db: Session = Depends(get_database_session)):
    """Validate and version defaults; existing AgentVersions are never modified."""
    return settings.save(db, principal, tenant_id, body.settings, body.expected_version)


@router.post('/runs/{run_id}/steer', status_code=202)
def steer(tenant_id: UUID, run_id: UUID, body: SteerInput,
          key: str = Header(alias='Idempotency-Key'), principal: Principal = Depends(get_principal), db: Session = Depends(get_database_session)):
    """Queue an idempotent correction to be persisted and injected at the next round boundary."""
    row = directives.submit(db, principal, tenant_id, run_id, body.content, key)
    return {'id': str(row.id), 'status': 'queued'}


@router.get('/memory')
def list_memory(tenant_id: UUID, principal: Principal = Depends(get_principal), db: Session = Depends(get_database_session)):
    """List owned published memory/SOP pointers and pending drafts for human review."""
    return memory.list_memory(db, principal, tenant_id)


@router.get('/memory/{entry_id}')
def read_memory(tenant_id: UUID, entry_id: UUID, version: int | None = None,
                principal: Principal = Depends(get_principal), db: Session = Depends(get_database_session)):
    """Read one authorized immutable memory version and provenance."""
    return memory.read(db, principal, tenant_id, entry_id, version)


@router.post('/memory-drafts/{draft_id}/review')
def review_memory(tenant_id: UUID, draft_id: UUID, body: MemoryReview,
                  principal: Principal = Depends(get_principal), db: Session = Depends(get_database_session)):
    """Publish an explicitly reviewed draft or reject it; model tools cannot call this service."""
    return memory.review(db, principal, tenant_id, draft_id, **body.model_dump())


@router.post('/memory/{entry_id}/restore')
def restore_memory(tenant_id: UUID, entry_id: UUID, body: MemoryRestore,
                   principal: Principal = Depends(get_principal), db: Session = Depends(get_database_session)):
    """Append a restored version only when the expected current version still matches."""
    return memory.restore(db, principal, tenant_id, entry_id, body.version, body.expected_version)


@router.delete('/memory/{entry_id}')
def archive_memory(tenant_id: UUID, entry_id: UUID,
                   principal: Principal = Depends(get_principal), db: Session = Depends(get_database_session)):
    """Remove owned memory from future navigation while preserving historical versions."""
    memory.archive(db, principal, tenant_id, entry_id)
    return {'status': 'archived'}


class ApprovalDecision(BaseModel):
    """A per-call human decision with optional schema-revalidated argument corrections."""
    approve: bool
    arguments: dict[str, Any] | None = None


@router.get('/runs/{run_id}/approvals')
def get_approvals(tenant_id: UUID, run_id: UUID, principal: Principal = Depends(get_principal), db: Session = Depends(get_database_session)):
    """Read only this owner's pending action prompts."""
    from nexus_platform.runs.approvals import list_pending
    return list_pending(db, principal, tenant_id, run_id)


@router.post('/runs/{run_id}/approvals/{approval_id}')
def resolve_approval(tenant_id: UUID, run_id: UUID, approval_id: UUID, body: ApprovalDecision,
                     principal: Principal = Depends(get_principal), db: Session = Depends(get_database_session)):
    """Resolve and requeue once; the worker rechecks resource authorization before invocation."""
    from nexus_platform.runs.approvals import resolve
    return resolve(db, principal, tenant_id, run_id, approval_id, body.approve, body.arguments)


class ModelBranch(BaseModel):
    """An explicit authorized target model; no hidden mutation of an existing Session."""
    model_profile_version_id: UUID


@router.post('/sessions/{session_id}/model-branch', status_code=201)
def model_branch(tenant_id: UUID, session_id: UUID, body: ModelBranch,
                 principal: Principal = Depends(get_principal), db: Session = Depends(get_database_session)):
    """Preserve authorized history in an idle model branch, leaving the source intact."""
    from nexus_platform.sessions.fork import fork
    return fork(db, principal, tenant_id, session_id, body.model_profile_version_id)
