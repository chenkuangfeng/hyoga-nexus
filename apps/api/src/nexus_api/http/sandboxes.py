"""Enterprise sandbox settings. Deployment credentials never enter the HTTP schema."""
from __future__ import annotations

from uuid import UUID

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
