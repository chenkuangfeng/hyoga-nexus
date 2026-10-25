"""Submission configuration snapshots; no mapped entities or credentials cross this boundary."""
from dataclasses import dataclass
from typing import Any
from uuid import UUID


@dataclass(frozen=True)
class AuthorizedMember:
    """Current user and membership role resolved within the write transaction."""
    user_id: UUID
    role: str


@dataclass(frozen=True)
class SubmissionSession:
    """Owner-scoped Session version and state read while holding its row lock."""
    id: UUID
    agent_version_id: UUID
    status: str


@dataclass(frozen=True)
class PublishedAgent:
    """Immutable AgentVersion values needed to freeze a Run's execution configuration."""
    id: UUID
    agent_id: UUID
    version: int
    content_hash: str
    runtime_type: str
    model_profile_version_id: UUID
    budgets: dict[str, Any]


@dataclass(frozen=True)
class BoundResource:
    """A published binding describes requested access; current grants still need checking."""
    id: UUID
    kind: str
    resource_id: str
    resource_version_id: str
    source_workspace_id: UUID
    binding_config: dict[str, Any]

    def snapshot(self) -> dict[str, Any]:
        """Use the existing persisted JSON keys; empty version means an unversioned reference."""
        return {
            "kind": self.kind, "resource_id": self.resource_id,
            "resource_version_id": self.resource_version_id or None,
            "source_workspace_id": str(self.source_workspace_id),
            "binding_id": str(self.id), "config": self.binding_config,
        }


@dataclass(frozen=True)
class PublishedModel:
    """Immutable profile version identifiers; only a credential reference is retained."""
    id: UUID
    profile_id: UUID
    content_hash: str
    credential_reference_id: UUID | None
