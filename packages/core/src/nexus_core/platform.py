"""Framework-neutral contracts shared by platform services and adapters."""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Protocol
from uuid import UUID


def new_id() -> UUID:
    """Create an RFC 9562 UUIDv7 without making core depend on a vendor package."""
    timestamp_ms = int(time.time_ns() // 1_000_000) & ((1 << 48) - 1)
    rand_a = secrets.randbits(12)
    rand_b = secrets.randbits(62)
    value = (timestamp_ms << 80) | (0x7 << 76) | (rand_a << 64) | (0b10 << 62) | rand_b
    return UUID(int=value)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


#: Reserved space that owns builtin skills and tools (openspec 2026-11-07-skill-evolution). It has no members,
#: cannot be signed in to and never appears in a space list; resources registered under it are usable from every
#: space, personal spaces included, without a grant.
SYSTEM_TENANT_ID = UUID("00000000-0000-7000-8000-000000000001")
#: Account that owns the system space (``created_by``). It has no identity or credential, so nobody can sign in as it.
SYSTEM_USER_ID = UUID("00000000-0000-7000-8000-000000000002")
#: Resource kinds that are effective in every space once registered under the system space.
GLOBAL_BUILTIN_KINDS = frozenset({"skill", "tool"})


class TenantRole(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    CONTRIBUTOR = "contributor"
    VIEWER = "viewer"


class MembershipStatus(StrEnum):
    ACTIVE = "active"
    REVOKED = "revoked"


class AgentStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    WAITING_INPUT = "waiting_input"
    WAITING_APPROVAL = "waiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"

    @property
    def terminal(self) -> bool:
        return self in {
            RunStatus.COMPLETED,
            RunStatus.FAILED,
            RunStatus.CANCELLED,
            RunStatus.INTERRUPTED,
        }


@dataclass(frozen=True, slots=True)
class Principal:
    """External identity presented to the platform.

    `issuer` names the provider (for example `wecom`, `password`). `scope` narrows the external
    id to a provider namespace such as a WeCom corp id; it is empty when the provider has none.
    """
    id: str
    issuer: str
    scope: str = ""


@dataclass(frozen=True, slots=True)
class ResourceReference:
    kind: str
    resource_id: str
    version_id: str | None = None


@dataclass(frozen=True, slots=True)
class CredentialRef:
    id: UUID
    backend: str
    handle: str
    scope: str


@dataclass(frozen=True, slots=True)
class RunEvent:
    event_id: UUID
    run_id: UUID
    sequence: int
    occurred_at: datetime
    kind: str
    schema_version: int
    payload: dict[str, object]


class ResourceAuthorizationPort(Protocol):
    """Adapter-facing contract that rechecks current grants at each operation."""

    def authorize(
        self,
        principal: Principal,
        tenant_id: UUID,
        run_id: UUID,
        binding_id: UUID,
        permission: str = "use",
    ) -> ResourceReference: ...
