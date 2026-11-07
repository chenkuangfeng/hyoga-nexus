"""Skill HTTP endpoints: list skills, read version metadata, and publish a new version (administrators).

Bodies and resource files are never returned by these routes; models read them through the Run.
Publishing applies the same rules as the service (SKILL.md format, file limits, scripts, dependencies).
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from nexus_core.platform import Principal
from nexus_platform.skills import service as skills
from nexus_api.dependencies.platform import get_database_session, get_principal

router = APIRouter(prefix="/api/v1")


class SkillPublishRequest(BaseModel):
    """SKILL.md text plus resource files keyed by relative path (``refs/...``, ``scripts/...``)."""
    skill_md: str = Field(min_length=1, max_length=64_000)
    files: dict[str, str] = Field(default_factory=dict)
    #: An administrator releases findings the release policy would otherwise stop (recorded in the audit log).
    acknowledge_findings: bool = False


@router.get("/tenants/{tenant_id}/skills")
def list_skills(tenant_id: UUID, principal: Principal = Depends(get_principal),
                db: Session = Depends(get_database_session)) -> list[dict[str, Any]]:
    """Skills visible in this Tenant. Requires active membership."""
    return skills.list_skills(db, principal, tenant_id)


@router.get("/tenants/{tenant_id}/skills/{name}/versions")
def skill_versions(tenant_id: UUID, name: str, principal: Principal = Depends(get_principal),
                   db: Session = Depends(get_database_session)) -> list[dict[str, Any]]:
    """Version metadata and hashes for one skill. Requires active membership."""
    return skills.skill_versions(db, principal, tenant_id, name)


@router.post("/tenants/{tenant_id}/skills", status_code=201)
def publish_skill(tenant_id: UUID, body: SkillPublishRequest, principal: Principal = Depends(get_principal),
                  db: Session = Depends(get_database_session)) -> dict[str, Any]:
    """Publish a new immutable version. Requires the tools-management permission (administrators)."""
    return skills.publish(db, principal, tenant_id, body.skill_md, body.files,
                          acknowledge_findings=body.acknowledge_findings)


@router.post("/platform/skills/import-builtin")
def import_builtin_skills(principal: Principal = Depends(get_principal), db: Session = Depends(get_database_session)):
    """Import the repository's builtin skills into the system space (platform administrators only).

    Builtin skills are assignable in every space. Unchanged folders are reported as ``unchanged``; changed ones
    become a new version, and agent versions that bound an earlier version keep it.
    """
    from nexus_platform.configuration import builtin_skills_dir
    return skills.import_builtin(db, principal, builtin_skills_dir())


@router.post("/tenants/{tenant_id}/skills/{name}/versions/{version}/rescan")
def rescan_skill_version(tenant_id: UUID, name: str, version: int, principal: Principal = Depends(get_principal),
                         db: Session = Depends(get_database_session)) -> dict[str, Any]:
    """Scan a published version again with the current scanner (administrators). Content is unchanged."""
    return skills.rescan(db, principal, tenant_id, name, version)
