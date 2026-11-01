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
            origin: str = 'foreground', source_message_ids: tuple[str, ...] = ()) -> dict[str, Any]:
    """Screen and record a draft inside the caller's Run transaction; the owner is the Run's principal."""
    return rules.propose(SqlMemoryRepository(db), tenant_id, owner_id, run_id, kind, diff, entry_id=entry_id,
                         base_version=base_version, origin=origin, source_message_ids=source_message_ids)


@_translate
def search(db, tenant_id: UUID, owner_id: UUID, query: str, limit: int = rules.SEARCH_LIMIT_DEFAULT) -> list[dict[str, Any]]:
    """Keyword search over the owner's live published entries; caller transaction, no commit."""
    return rules.search(SqlMemoryRepository(db), tenant_id, owner_id, query, limit=limit, now=utc_now())


@_translate
def set_availability(db, principal: Principal, tenant_id: UUID, entry_id: UUID, *,
                     enabled: bool | None = None, valid_until: Any = UNSET) -> dict[str, Any]:
    with db.begin():
        user, _ = context(db, principal, tenant_id)
        return rules.set_availability(SqlMemoryRepository(db), user.id, tenant_id, entry_id,
                                      enabled=enabled, valid_until=valid_until)


@_translate
def list_memory(db, principal: Principal, tenant_id: UUID) -> dict[str, Any]:
    with db.begin():
        user, _ = context(db, principal, tenant_id)
        return rules.list_memory(SqlMemoryRepository(db), user.id, tenant_id)


@_translate
def read(db, principal: Principal, tenant_id: UUID, entry_id: UUID, version: int | None = None) -> dict[str, Any]:
    with db.begin():
        user, _ = context(db, principal, tenant_id)
        return rules.read(SqlMemoryRepository(db), user.id, tenant_id, entry_id, version)


@_translate
def read_for_run(db, tenant_id: UUID, owner_id: UUID, entry_id: UUID, run_id: UUID) -> str:
    """Model tool read inside an open run transaction; the run owner must already be verified."""
    return rules.read_for_run(SqlMemoryRepository(db), tenant_id, owner_id, entry_id, run_id)


@_translate
def review(db, principal: Principal, tenant_id: UUID, draft_id: UUID, *, approve: bool, title: str,
           entry_id: UUID | None = None, expected_version: int = 0, project: str = '') -> dict[str, Any]:
    with db.begin():
        user, _ = context(db, principal, tenant_id)
        return rules.review(SqlMemoryRepository(db), user.id, tenant_id, draft_id, approve=approve,
                            title=title, entry_id=entry_id, expected_version=expected_version, project=project)


@_translate
def archive(db, principal: Principal, tenant_id: UUID, entry_id: UUID) -> None:
    with db.begin():
        user, _ = context(db, principal, tenant_id)
        rules.archive(SqlMemoryRepository(db), user.id, tenant_id, entry_id)


@_translate
def restore(db, principal: Principal, tenant_id: UUID, entry_id: UUID, version: int,
            expected_version: int) -> dict[str, Any]:
    with db.begin():
        user, _ = context(db, principal, tenant_id)
        return rules.restore(SqlMemoryRepository(db), user.id, tenant_id, entry_id, version, expected_version)
