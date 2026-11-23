"""Enterprise sandbox settings. Deployment credentials never enter the HTTP schema."""
from __future__ import annotations

from uuid import UUID
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from nexus_api.dependencies.platform import get_database_session, get_principal
from nexus_core.platform import Principal
from nexus_platform.runs import sandbox_profiles

router = APIRouter(prefix='/api/v1/tenants/{tenant_id}/admin/sandboxes', tags=['Sandbox profiles'])


class SandboxPolicyInput(BaseModel):
    """Editable policy for an already provisioned execution profile."""

    model_config = ConfigDict(extra='forbid', strict=True)
    paused: bool
    exec_timeout_max_seconds: int = Field(ge=1, le=3600)
    skill_timeout_seconds: int = Field(ge=1, le=3600)
    skill_timeout_max_seconds: int = Field(ge=1, le=3600)


@router.get('/{name}')
def get_sandbox(tenant_id: UUID, name: str, principal: Principal = Depends(get_principal),
                db: Session = Depends(get_database_session)):
    """Show availability, capabilities and the last worker-side isolation report."""
    return sandbox_profiles.profile_detail(db, principal, tenant_id, name)


@router.put('/{name}/policy')
def put_sandbox_policy(tenant_id: UUID, name: str, body: SandboxPolicyInput,
                       principal: Principal = Depends(get_principal), db: Session = Depends(get_database_session)):
    """Change the shared policy of a preconfigured profile."""
    return sandbox_profiles.update_policy(db, principal, tenant_id, name, body.model_dump())


@router.post('/{name}/connect')
def connect_sandbox(tenant_id: UUID, name: str, principal: Principal = Depends(get_principal),
                    db: Session = Depends(get_database_session)):
    """Validate gateway capabilities and bind this profile to its policy revision."""
    return sandbox_profiles.connect_profile(db, principal, tenant_id, name)


@router.get('/{name}/executions')
def sandbox_executions(tenant_id: UUID, name: str, principal: Principal = Depends(get_principal),
                       db: Session = Depends(get_database_session)):
    """Read active executions and pending cleanup for platform administrators."""
    return sandbox_profiles.gateway_operations(db, principal, tenant_id, name)


@router.post('/{name}/executions/{request_id}/cleanup')
def cleanup_execution(tenant_id: UUID, name: str, request_id: str,
                      principal: Principal = Depends(get_principal), db: Session = Depends(get_database_session)):
    """Retry teardown without replaying the command."""
    return sandbox_profiles.gateway_operations(db, principal, tenant_id, name, request_id)


class ProviderInput(BaseModel):
    """Provider template settings; an omitted key retains the encrypted gateway credential."""
    model_config = ConfigDict(extra='forbid')
    type: Literal['e2b', 'cubesandbox']
    template: str = Field(min_length=1, max_length=256)
    domain: str = Field(min_length=1, max_length=256)
    revision: str = Field(min_length=1, max_length=256)
    api_key: str | None = Field(default=None, max_length=1024)


@router.get('/{name}/provider')
def read_provider(tenant_id: UUID, name: str, principal: Principal = Depends(get_principal),
                  db: Session = Depends(get_database_session)):
    """Read credential-redacted provider provisioning."""
    return sandbox_profiles.provider_settings(db, principal, tenant_id, name)


@router.put('/{name}/provider')
def write_provider(tenant_id: UUID, name: str, body: ProviderInput,
                   principal: Principal = Depends(get_principal), db: Session = Depends(get_database_session)):
    """Save provider settings and invalidate the previous connection binding."""
    return sandbox_profiles.provider_settings(db, principal, tenant_id, name, body.model_dump())
