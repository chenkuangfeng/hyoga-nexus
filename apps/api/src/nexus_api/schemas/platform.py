from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class TenantCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)


class TenantUpdate(BaseModel):
    """Partial update of the current space: fields left out keep their value; `description: ""` clears it."""

    name: str | None = Field(default=None, max_length=160)
    description: str | None = Field(default=None, max_length=500)


class TenantView(BaseModel):
    id: UUID
    name: str
    kind: str = "enterprise"
    description: str | None = None
    role: str
    status: str
    created_at: datetime


class MemberCreate(BaseModel):
    issuer: str = Field(min_length=1, max_length=128)
    subject: str = Field(min_length=1, max_length=255)
    role: Literal["admin", "contributor", "viewer"] = "contributor"


class MemberRoleUpdate(BaseModel):
    role: Literal["owner", "admin", "contributor", "viewer"]


class MemberView(BaseModel):
    """An active membership. `email`, `username` and `display_name` come from the user, so member lists can
    show who each person is; they are None when the user has no such field."""

    tenant_id: UUID
    user_id: UUID
    role: str
    status: str
    joined_at: datetime
    email: str | None = None
    username: str | None = None
    display_name: str | None = None


class CredentialReferenceInput(BaseModel):
    backend: str = Field(min_length=1, max_length=80)
    handle: str = Field(min_length=1, max_length=512)


class CredentialReferenceView(BaseModel):
    id: UUID
    tenant_id: UUID
    backend: str
    status: str
    created_at: datetime


class ModelProfileCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    provider: str = Field(min_length=1, max_length=100)
    model_name: str = Field(min_length=1, max_length=160)
    options: dict[str, Any] = Field(default_factory=dict)
    credential_reference_id: UUID | None = None


class ModelProfileUpdate(BaseModel):
    model_name: str = Field(min_length=1, max_length=160)
    options: dict[str, Any] = Field(default_factory=dict)
    credential_reference_id: UUID | None = None


class ModelProfileVersionView(BaseModel):
    id: UUID
    profile_id: UUID
    version: int
    model_name: str
    options: dict[str, Any]
    credential_reference_id: UUID | None
    content_hash: str
    created_at: datetime


class ModelProfileView(BaseModel):
    id: UUID
    tenant_id: UUID
    name: str
    provider: str
    current_version: ModelProfileVersionView | None
    created_at: datetime


class ResourceBindingInput(BaseModel):
    kind: str = Field(min_length=1, max_length=64)
    resource_id: str = Field(min_length=1, max_length=255)
    resource_version_id: str | None = Field(default=None, max_length=255)
    source_tenant_id: UUID | None = None
    config: dict[str, Any] = Field(default_factory=dict)


class AgentDraftInput(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=2000)
    runtime_type: Literal["native", "codex", "claude_code", "deepseek_harness"] = "native"
    instructions: str = Field(default="", max_length=100000)
    model_profile_version_id: UUID
    budgets: dict[str, Any] = Field(default_factory=dict)
    resource_bindings: list[ResourceBindingInput] = Field(default_factory=list)


class AgentVersionView(BaseModel):
    id: UUID
    agent_id: UUID
    version: int
    name: str
    description: str
    runtime_type: str
    model_profile_version_id: UUID
    budgets: dict[str, Any]
    content_hash: str
    published_at: datetime


class AdminAgentView(BaseModel):
    """An agent as listed for the platform administrator's session filter."""
    id: UUID
    tenant_id: UUID
    name: str
    published_version_id: UUID | None


class AgentView(BaseModel):
    id: UUID
    tenant_id: UUID
    name: str
    description: str
    status: str
    published_version_id: UUID | None
    version_counter: int
    current_version: AgentVersionView | None = None
    runtime_type: str
    instructions: str
    model_profile_version_id: UUID | None
    budgets: dict[str, Any]
    resource_bindings: list[dict[str, Any]]
    created_at: datetime
    updated_at: datetime


class MemorySnapshotView(BaseModel):
    """Whether a session has a frozen memory index, and whether published memory has changed since."""
    exists: bool
    created_at: datetime | None = None
    stale: bool = False


class SessionCreate(BaseModel):
    agent_version_id: UUID
    title: str = Field(default="", max_length=255)


class SessionView(BaseModel):
    id: UUID
    tenant_id: UUID
    owner_user_id: UUID
    agent_version_id: UUID
    runtime_type: str
    title: str
    status: str
    created_at: datetime
    updated_at: datetime


class RunCreate(BaseModel):
    message: str = Field(min_length=1, max_length=100000)


class RunView(BaseModel):
    id: UUID
    tenant_id: UUID
    session_id: UUID
    principal_id: UUID
    status: str
    attempt: int
    error_code: str | None
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    ended_at: datetime | None
    # 1-based place in the session queue while queued; None otherwise.
    queue_position: int | None = None
    # True while the newest run.watchdog_alert has no acknowledgement or later progress.
    attention_required: bool = False


class RunEventView(BaseModel):
    event_id: UUID
    run_id: UUID
    sequence: int
    event_type: str
    schema_version: int
    payload: dict[str, Any]
    occurred_at: datetime
    #: True for live-only text (``message.delta`` on a channel that keeps it off the database): it has no
    #: stored sequence, so ``sequence`` is only the position of the last stored event before it.
    ephemeral: bool = False


class ResourceGrantCreate(BaseModel):
    source_tenant_id: UUID
    kind: str = Field(min_length=1, max_length=64)
    resource_id: str = Field(min_length=1, max_length=255)
    permissions: list[Literal["read", "use"]] = Field(min_length=1)


class ResourceGrantView(BaseModel):
    id: UUID
    source_tenant_id: UUID
    target_tenant_id: UUID
    kind: str
    resource_id: str
    permissions: list[str]
    created_at: datetime


class InputResponse(BaseModel):
    input_request_id: UUID
    response: str = Field(min_length=1, max_length=100000)


class RoleInput(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    menus: list[str] = Field(default_factory=list, max_length=32)
    apis: list[str] = Field(default_factory=list, max_length=64)


class RoleGrantsInput(BaseModel):
    menus: list[str] = Field(default_factory=list, max_length=32)
    apis: list[str] = Field(default_factory=list, max_length=64)


class RoleView(BaseModel):
    id: UUID
    tenant_id: UUID
    name: str
    menus: list[str]
    apis: list[str]
    created_at: datetime
    updated_at: datetime


class PermissionsView(BaseModel):
    menus: list[str]
    apis: list[str]


class PermissionCatalogView(BaseModel):
    menus: list[str]
    apis: list[str]


class AgentGrantsInput(BaseModel):
    permissions: list[Literal["view", "run", "edit", "publish", "manage"]] = Field(default_factory=list, max_length=5)


class AgentGrantsView(BaseModel):
    role_id: UUID
    agent_id: UUID
    permissions: list[str]


class RoleAssignmentView(BaseModel):
    user_id: UUID
    role_id: UUID


class AgentGrantRowView(BaseModel):
    role_id: UUID
    agent_id: UUID
    permission: str


class AccountCreate(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    email: str = Field(min_length=3, max_length=255)
    display_name: str = Field(default="", max_length=160)
    password: str = Field(min_length=10, max_length=256)
    role: Literal["admin", "contributor", "viewer"] = "contributor"


class AccountView(BaseModel):
    user_id: UUID
    username: str
    role: str
