"""Native user preferences, owned memory publication and durable runtime corrections."""
from datetime import datetime
from typing import Any
from uuid import UUID
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from nexus_core.platform import Principal
from nexus_api.dependencies.platform import get_principal, get_database_session
from nexus_platform.runs import settings, directives
from nexus_platform.memory import capture as memory_capture
from nexus_platform.memory import consolidation as memory_consolidation
from nexus_platform.memory import service as memory
from nexus_platform.memory import switches as memory_switches

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
    #: Optional override of the draft's importance (1-5); omitted keeps the draft's or the entry's value.
    importance: int | None = Field(default=None, ge=1, le=5)


class MemoryRestore(BaseModel):
    """Restore a historical version without overwriting newer history."""
    version: int = Field(ge=1)
    expected_version: int = Field(ge=1)


class MemoryAvailability(BaseModel):
    """Enable or disable an entry, and set or clear its validity end. Omitted fields are left unchanged."""
    enabled: bool | None = None
    valid_until: datetime | None = None


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


class MemoryCaptureUpdate(BaseModel):
    """Enabling requires a capture model; the model is authorized again on every extraction."""
    enabled: bool
    model_profile_version_id: UUID | None = None
    capacity_policy: Literal['reject', 'evict_auto'] = 'reject'


@router.get('/memory-capture')
def get_memory_capture(tenant_id: UUID, principal: Principal = Depends(get_principal), db: Session = Depends(get_database_session)):
    """The caller's automatic memory capture settings; off unless the caller enabled it."""
    return memory_capture.capture_settings(db, principal, tenant_id)


@router.get('/memory-capture/usage')
def get_memory_capture_usage(tenant_id: UUID, principal: Principal = Depends(get_principal),
                             db: Session = Depends(get_database_session)):
    """Token usage of the caller's automatic extraction calls over the last 30 days."""
    return memory_capture.capture_usage(db, principal, tenant_id)


@router.put('/memory-capture')
def update_memory_capture(tenant_id: UUID, body: MemoryCaptureUpdate, principal: Principal = Depends(get_principal),
                          db: Session = Depends(get_database_session)):
    """Turn automatic capture on or off for the caller in this space."""
    try:
        return memory_capture.set_capture(db, principal, tenant_id, enabled=body.enabled,
                                          model_profile_version_id=body.model_profile_version_id,
                                          capacity_policy=body.capacity_policy)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


class MemorySpaceSettingsUpdate(BaseModel):
    """Space-wide long-term memory switch and write mode (`explicit` never queues automatic capture)."""
    enabled: bool
    write_mode: Literal['explicit', 'auto'] = 'auto'
    #: Custom extraction rules (at most 1000 characters); omitted keeps the current rules, '' clears them.
    extract_instructions: str | None = Field(default=None, max_length=1000)
    #: Embedding model for semantic memory recall; null turns it off, omitted keeps the current choice.
    embedding_model_version_id: UUID | None = None
    #: Conversations a subject must come up in before it is proposed as an interest (2-10); omitted keeps it.
    interest_threshold: int | None = Field(default=None, ge=2, le=10)
    #: Registered external memory provider; null for built-in only, omitted keeps the current choice.
    memory_provider: str | None = Field(default=None, max_length=64)


class MemoryPreferencesUpdate(BaseModel):
    """The caller's own long-term memory switch in this space."""
    memory_enabled: bool


@router.get('/memory-settings')
def get_memory_settings(tenant_id: UUID, principal: Principal = Depends(get_principal),
                        db: Session = Depends(get_database_session)):
    """Space memory settings; any member may read, `can_edit` is true for owners and admins."""
    return memory_switches.space_settings(db, principal, tenant_id)


@router.put('/memory-settings')
def update_memory_settings(tenant_id: UUID, body: MemorySpaceSettingsUpdate, principal: Principal = Depends(get_principal),
                           db: Session = Depends(get_database_session)):
    """Turn long-term memory on or off for the whole space and choose the write mode (owners and admins)."""
    from nexus_memory.ports import UNSET
    embedding = body.embedding_model_version_id if 'embedding_model_version_id' in body.model_fields_set else UNSET
    return memory_switches.set_space_settings(db, principal, tenant_id, enabled=body.enabled, write_mode=body.write_mode,
                                             extract_instructions=body.extract_instructions,
                                             embedding_model_version_id=embedding,
                                             interest_threshold=body.interest_threshold,
                                             memory_provider=body.memory_provider if 'memory_provider' in body.model_fields_set else UNSET)


@router.get('/memory-preferences')
def get_memory_preferences(tenant_id: UUID, principal: Principal = Depends(get_principal),
                           db: Session = Depends(get_database_session)):
    """The caller's own switch, whether memory is effective for them, and why not (`reason`)."""
    return memory_switches.preferences(db, principal, tenant_id)


@router.put('/memory-preferences')
def update_memory_preferences(tenant_id: UUID, body: MemoryPreferencesUpdate, principal: Principal = Depends(get_principal),
                              db: Session = Depends(get_database_session)):
    """Turn the caller's own long-term memory on or off; existing entries and drafts are kept."""
    return memory_switches.set_preferences(db, principal, tenant_id, memory_enabled=body.memory_enabled)


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


@router.patch('/memory/{entry_id}')
def update_memory_availability(tenant_id: UUID, entry_id: UUID, body: MemoryAvailability,
                               principal: Principal = Depends(get_principal),
                               db: Session = Depends(get_database_session)):
    """Enable/disable an owned entry or set its validity end; archiving stays a separate action."""
    from nexus_memory.ports import UNSET
    valid_until: Any = body.valid_until if 'valid_until' in body.model_fields_set else UNSET
    enabled = body.enabled if 'enabled' in body.model_fields_set else None
    return memory.set_availability(db, principal, tenant_id, entry_id, enabled=enabled, valid_until=valid_until)


@router.get('/memory-topics')
def list_memory_topics(tenant_id: UUID, principal: Principal = Depends(get_principal),
                       db: Session = Depends(get_database_session)):
    """Subjects the caller keeps bringing up, with conversation counts toward the interest threshold."""
    from nexus_platform.memory.interests import list_topics
    return list_topics(db, principal, tenant_id)


@router.get('/memory-doc-affinity')
def list_memory_doc_affinity(tenant_id: UUID, principal: Principal = Depends(get_principal),
                             db: Session = Depends(get_database_session)):
    """Knowledge documents the caller's answers keep citing; documents with 2+ citations rank slightly higher."""
    from nexus_platform.memory.doc_affinity import list_affinity
    return list_affinity(db, principal, tenant_id)


@router.delete('/memory-doc-affinity')
def clear_memory_doc_affinity(tenant_id: UUID, document_id: UUID | None = None,
                              principal: Principal = Depends(get_principal), db: Session = Depends(get_database_session)):
    """Forget one document's counter (``document_id``) or all of the caller's counters."""
    from nexus_platform.memory.doc_affinity import clear
    return {'deleted': clear(db, principal, tenant_id, document_id)}


@router.post('/memory-consolidation', status_code=202)
def request_memory_consolidation(tenant_id: UUID, principal: Principal = Depends(get_principal),
                                 db: Session = Depends(get_database_session)):
    """Ask for a consolidation pass over the caller's memory; the worker records merge drafts for review.

    409 `memory_disabled`, `capture_model_required` (no capture model saved) or `too_soon` (once a minute).
    """
    return memory_consolidation.request_consolidation(db, principal, tenant_id)


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
    #: `session` also allows later calls of this tool in this session (not for destructive or guarded calls).
    remember: Literal['once', 'session'] = 'once'


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
    return resolve(db, principal, tenant_id, run_id, approval_id, body.approve, body.arguments, body.remember)


@router.get('/sessions/{session_id}/tool-grants')
def get_tool_grants(tenant_id: UUID, session_id: UUID, principal: Principal = Depends(get_principal),
                    db: Session = Depends(get_database_session)):
    """Tools the caller allowed for the rest of this session (owner only)."""
    from nexus_platform.runs.approvals import list_grants
    return list_grants(db, principal, tenant_id, session_id)


@router.delete('/sessions/{session_id}/tool-grants/{grant_id}')
def delete_tool_grant(tenant_id: UUID, session_id: UUID, grant_id: UUID, principal: Principal = Depends(get_principal),
                      db: Session = Depends(get_database_session)):
    """Revoke a session grant; the next call of that tool asks again."""
    from nexus_platform.runs.approvals import revoke_grant
    return revoke_grant(db, principal, tenant_id, session_id, grant_id)


class ModelBranch(BaseModel):
    """An explicit authorized target model; no hidden mutation of an existing Session."""
    model_profile_version_id: UUID


@router.post('/sessions/{session_id}/model-branch', status_code=201)
def model_branch(tenant_id: UUID, session_id: UUID, body: ModelBranch,
                 principal: Principal = Depends(get_principal), db: Session = Depends(get_database_session)):
    """Preserve authorized history in an idle model branch, leaving the source intact."""
    from nexus_platform.sessions.fork import fork
    return fork(db, principal, tenant_id, session_id, body.model_profile_version_id)
