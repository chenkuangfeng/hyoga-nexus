"""Platform facade over `nexus_memory`: resolves principals, opens the transaction and maps errors.

API handlers and runs call these functions with a database session. The memory rules
themselves live in `nexus_memory.service`; this module only adapts them to platform
conventions (`NotFound`/`Conflict` responses, `context()` for the acting user).
"""
from __future__ import annotations

from functools import wraps
from typing import Any, Callable
from uuid import UUID

from nexus_core.platform import Principal
from nexus_memory import service as rules
from nexus_memory.ports import MemoryConflict, MemoryNotFound
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


def index(db, workspace_id: UUID, user_id: UUID, project: str = '') -> str:
    """Bounded published index for prompt injection; caller transaction, no commit."""
    return rules.index(SqlMemoryRepository(db), workspace_id, user_id, project)


@_translate
def list_memory(db, principal: Principal, workspace_id: UUID) -> dict[str, Any]:
    with db.begin():
        user, _ = context(db, principal, workspace_id)
        return rules.list_memory(SqlMemoryRepository(db), user.id, workspace_id)


@_translate
def read(db, principal: Principal, workspace_id: UUID, entry_id: UUID, version: int | None = None) -> dict[str, Any]:
    with db.begin():
        user, _ = context(db, principal, workspace_id)
        return rules.read(SqlMemoryRepository(db), user.id, workspace_id, entry_id, version)


@_translate
def read_for_run(db, workspace_id: UUID, owner_id: UUID, entry_id: UUID, run_id: UUID) -> str:
    """Model tool read inside an open run transaction; the run owner must already be verified."""
    return rules.read_for_run(SqlMemoryRepository(db), workspace_id, owner_id, entry_id, run_id)


@_translate
def review(db, principal: Principal, workspace_id: UUID, draft_id: UUID, *, approve: bool, title: str,
           entry_id: UUID | None = None, expected_version: int = 0, project: str = '') -> dict[str, Any]:
    with db.begin():
        user, _ = context(db, principal, workspace_id)
        return rules.review(SqlMemoryRepository(db), user.id, workspace_id, draft_id, approve=approve,
                            title=title, entry_id=entry_id, expected_version=expected_version, project=project)


@_translate
def archive(db, principal: Principal, workspace_id: UUID, entry_id: UUID) -> None:
    with db.begin():
        user, _ = context(db, principal, workspace_id)
        rules.archive(SqlMemoryRepository(db), user.id, workspace_id, entry_id)


@_translate
def restore(db, principal: Principal, workspace_id: UUID, entry_id: UUID, version: int,
            expected_version: int) -> dict[str, Any]:
    with db.begin():
        user, _ = context(db, principal, workspace_id)
        return rules.restore(SqlMemoryRepository(db), user.id, workspace_id, entry_id, version, expected_version)
