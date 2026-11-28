"""Platform facade over `nexus_memory`: resolves principals, opens the transaction and maps errors.

API handlers and runs call these functions with a database session. The memory rules
themselves live in `nexus_memory.service`; this module only adapts them to platform
conventions (`NotFound`/`Conflict` responses, `context()` for the acting user).
"""
from __future__ import annotations

from functools import wraps
from typing import Any, Callable
from uuid import UUID

from nexus_core.platform import Principal, utc_now
from nexus_memory import service as rules
from nexus_memory.ports import UNSET, MemoryConflict, MemoryNotFound
from nexus_platform.errors import Conflict, NotFound
from nexus_platform.models.provider_settings import context

from .repository import SqlMemoryRepository


def _translate(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Re-raise memory-domain denials as the platform exceptions the API maps to HTTP."""
    @wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return fn(*args, **kwargs)
        except MemoryNotFound as exc:
            raise NotFound(str(exc)) from exc
        except MemoryConflict as exc:
            raise Conflict(str(exc)) from exc
    return wrapper


def index(db, tenant_id: UUID, user_id: UUID, project: str = '') -> str:
    """Bounded published index for prompt injection (live entries only); caller transaction, no commit."""
    return rules.index(SqlMemoryRepository(db), tenant_id, user_id, project, now=utc_now())


@_translate
def propose(db, tenant_id: UUID, owner_id: UUID, run_id: UUID, kind: str, diff: str, *,
            entry_id: UUID | None = None, base_version: int | None = None,
            origin: str = 'foreground', source_message_ids: tuple[str, ...] = (), **meta: Any) -> dict[str, Any]:
    """Screen and record a draft inside the caller's Run transaction; the owner is the Run's principal.

    `meta` forwards the optional extraction fields of `nexus_memory.service.propose` (`topic`,
    `importance`, `confidence`, `valid_until`, `evidence`).
    """
    return rules.propose(SqlMemoryRepository(db), tenant_id, owner_id, run_id, kind, diff, entry_id=entry_id,
                         base_version=base_version, origin=origin, source_message_ids=source_message_ids, **meta)


@_translate
def search(db, tenant_id: UUID, owner_id: UUID, query: str, limit: int = rules.SEARCH_LIMIT_DEFAULT,
           vector_ranking: list[UUID] | None = None) -> list[dict[str, Any]]:
    """Keyword search over the owner's live published entries, fused with `vector_ranking` when given
    (stage 5, D2); caller transaction, no commit."""
    return rules.search(SqlMemoryRepository(db), tenant_id, owner_id, query, limit=limit, now=utc_now(),
                        vector_ranking=vector_ranking)


@_translate
def set_availability(db, principal: Principal, tenant_id: UUID, entry_id: UUID, *,
                     enabled: bool | None = None, valid_until: Any = UNSET) -> dict[str, Any]:
    with db.begin():
        user, _ = context(db, principal, tenant_id)
        return rules.set_availability(SqlMemoryRepository(db), user.id, tenant_id, entry_id,
                                      enabled=enabled, valid_until=valid_until)


@_translate
def edit_entry(db, principal: Principal, tenant_id: UUID, entry_id: UUID, *, content: str,
               expected_version: int, title: str | None = None, importance: int | None = None) -> dict[str, Any]:
    with db.begin():
        user, _ = context(db, principal, tenant_id)
        return rules.edit_entry(SqlMemoryRepository(db), user.id, tenant_id, entry_id,
                                content=content, expected_version=expected_version,
                                title=title, importance=importance)


@_translate
def list_memory(db, principal: Principal, tenant_id: UUID) -> dict[str, Any]:
    with db.begin():
        user, _ = context(db, principal, tenant_id)
        return rules.list_memory(SqlMemoryRepository(db), user.id, tenant_id)


@_translate
def read(db, principal: Principal, tenant_id: UUID, entry_id: UUID, version: int | None = None) -> dict[str, Any]:
    with db.begin():
        user, _ = context(db, principal, tenant_id)
        result = rules.read(SqlMemoryRepository(db), user.id, tenant_id, entry_id, version)
        if result.get('source_run_id') == 'None':
            result['source_run_id'] = None
        return result


@_translate
def read_for_run(db, tenant_id: UUID, owner_id: UUID, entry_id: UUID, run_id: UUID) -> str:
    """Model tool read inside an open run transaction; the run owner must already be verified."""
    return rules.read_for_run(SqlMemoryRepository(db), tenant_id, owner_id, entry_id, run_id)


@_translate
def read_for_principal(db, tenant_id: UUID, owner_id: UUID, entry_id: UUID) -> str:
    """Read one owned published entry for an outbound MCP endpoint (stateless; no Run)."""
    return rules.read_for_principal(SqlMemoryRepository(db), tenant_id, owner_id, entry_id)


@_translate
def review(db, principal: Principal, tenant_id: UUID, draft_id: UUID, *, approve: bool, title: str,
           entry_id: UUID | None = None, expected_version: int = 0, project: str = '',
           importance: int | None = None) -> dict[str, Any]:
    with db.begin():
        user, _ = context(db, principal, tenant_id)
        return rules.review(SqlMemoryRepository(db), user.id, tenant_id, draft_id, approve=approve,
                            title=title, entry_id=entry_id, expected_version=expected_version, project=project,
                            importance=importance)


@_translate
def archive(db, principal: Principal, tenant_id: UUID, entry_id: UUID) -> None:
    with db.begin():
        user, _ = context(db, principal, tenant_id)
        rules.archive(SqlMemoryRepository(db), user.id, tenant_id, entry_id)


@_translate
def clear(db, principal: Principal, tenant_id: UUID) -> dict[str, int]:
    """Archive published entries and reject pending drafts while retaining immutable history."""
    from sqlalchemy import delete
    from nexus_platform.authz.audit import audit
    from nexus_platform.persistence.models import MemoryTopicStatRecord
    with db.begin():
        user, _ = context(db, principal, tenant_id)
        repo = SqlMemoryRepository(db)
        entries = repo.published_entries(tenant_id, user.id, '')
        for entry in entries:
            rules.archive(repo, user.id, tenant_id, entry.id)
        drafts = repo.pending_drafts(tenant_id, user.id)
        for draft in drafts:
            repo.set_draft_status(draft.id, 'rejected')
        db.execute(delete(MemoryTopicStatRecord).where(
            MemoryTopicStatRecord.tenant_id == tenant_id,
            MemoryTopicStatRecord.owner_user_id == user.id))
        audit(db, tenant_id, user.id, 'memory.cleared', 'memory', '',
              {'archived_entries': len(entries), 'rejected_drafts': len(drafts)})
        return {'removed': len(entries), 'drafts': len(drafts)}


@_translate
def restore(db, principal: Principal, tenant_id: UUID, entry_id: UUID, version: int,
            expected_version: int) -> dict[str, Any]:
    with db.begin():
        user, _ = context(db, principal, tenant_id)
        return rules.restore(SqlMemoryRepository(db), user.id, tenant_id, entry_id, version, expected_version)


@_translate
def create_manual(db, principal: Principal, tenant_id: UUID, *, title: str, kind: str,
                  content: str, importance: int = 3) -> dict[str, Any]:
    """Publish a user's explicit form submission atomically, retaining truthful manual provenance.

    No Run is fabricated. Screening, deduplication, tombstones and publication budgets still apply;
    failure rolls back both the manual draft and its publication.
    """
    from nexus_core.platform import new_id
    from nexus_memory import text
    from nexus_platform.persistence.models import MemoryDraftRecord

    with db.begin():
        user, _ = context(db, principal, tenant_id)
        if not title.strip() or not content.strip() or kind not in rules.KIND_VALUES:
            raise ValueError('Memory title, content or kind is invalid')
        screened = text.screen(content)
        if screened.threats:
            raise Conflict('Memory content rejected')
        fingerprint = text.fingerprint(screened.text)
        repo = SqlMemoryRepository(db)
        if repo.is_tombstoned(tenant_id, user.id, fingerprint) or repo.find_duplicate(tenant_id, user.id, fingerprint):
            raise Conflict('Memory already exists or was previously rejected')
        draft = MemoryDraftRecord(id=new_id(), tenant_id=tenant_id, source_run_id=None,
                                  scope=f'user:{user.id}', kind=kind, diff=screened.text,
                                  status='pending_review', created_at=utc_now(), origin='manual',
                                  fingerprint=fingerprint, importance=importance)
        db.add(draft)
        db.flush()
        return rules.review(repo, user.id, tenant_id, draft.id, approve=True,
                            title=title.strip(), importance=importance)
