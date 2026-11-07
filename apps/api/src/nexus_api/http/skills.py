"""Skill HTTP endpoints: list skills, read version metadata, and publish a new version (administrators).

Bodies and resource files are never returned by these routes; models read them through the Run.
Publishing applies the same rules as the service (SKILL.md format, file limits, scripts, dependencies).
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from nexus_core.platform import Principal
from nexus_platform.errors import InvalidConfiguration
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
def list_skills(tenant_id: UUID, sandbox_profile: str | None = Query(default=None, max_length=32),
                principal: Principal = Depends(get_principal),
                db: Session = Depends(get_database_session)) -> list[dict[str, Any]]:
    """Skills visible in this Tenant. Requires active membership.

    ``sandbox_profile`` (empty = the deployment's default) adds ``run`` to each skill that ships scripts: whether
    they can run on that sandbox profile and, when not, the reason.
    """
    return skills.list_skills(db, principal, tenant_id, sandbox_profile)


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


@router.post("/tenants/{tenant_id}/skills/upload", status_code=201)
async def upload_skill(tenant_id: UUID, request: Request, acknowledge_findings: bool = False,
                       sandbox_profile: str | None = Query(default=None, max_length=32),
                       principal: Principal = Depends(get_principal),
                       db: Session = Depends(get_database_session)) -> dict[str, Any]:
    """Install a skill from a zip sent as the raw request body (``application/zip``). Administrators only.

    The body is read in chunks and stopped at the upload limit, so an oversized request never sits in memory.
    The archive is checked (entries, sizes, paths, links, compression ratio) before anything is read from it.
    """
    from nexus_skills.bundle import MAX_UPLOAD_BYTES
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_UPLOAD_BYTES:
        raise InvalidConfiguration("bundle_too_large")
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_UPLOAD_BYTES:
            raise InvalidConfiguration("bundle_too_large")
        chunks.append(chunk)
    return skills.install_bundle(db, principal, tenant_id, b"".join(chunks), acknowledge_findings=acknowledge_findings,
                                 profile=sandbox_profile)


class RemoteInstallRequest(BaseModel):
    """A remote source: ``https://github.com/o/r[/tree/ref/dir]``, ``github:o/r/dir@ref``, a GitLab project URL,
    ``https://skills.sh/o/r/skill``, ``clawhub:slug[@version]`` or a direct https link to a zip."""
    source: str = Field(min_length=1, max_length=500)
    #: Must be true: the caller has shown the administrator what will be fetched by this server.
    confirm: bool = False
    acknowledge_findings: bool = False


@router.post("/tenants/{tenant_id}/skills/install-remote", status_code=201)
def install_remote_skill(tenant_id: UUID, body: RemoteInstallRequest, principal: Principal = Depends(get_principal),
                         db: Session = Depends(get_database_session)) -> dict[str, Any]:
    """Fetch a skill from a remote source and install it as a new version. Administrators; always needs ``confirm``."""
    from nexus_platform.skills import remote
    return remote.install_remote(db, principal, tenant_id, body.source, confirm=body.confirm,
                                 acknowledge_findings=body.acknowledge_findings)


@router.post("/tenants/{tenant_id}/skills/{name}/check-update")
def check_skill_update(tenant_id: UUID, name: str, principal: Principal = Depends(get_principal),
                       db: Session = Depends(get_database_session)) -> dict[str, Any]:
    """Look at the remote source an installed skill came from and say whether it changed. Applies nothing."""
    from nexus_platform.skills import remote
    return remote.check_update(db, principal, tenant_id, name)


@router.get("/tenants/{tenant_id}/skills/{name}/versions/{version}/install")
def skill_install_status(tenant_id: UUID, name: str, version: int, principal: Principal = Depends(get_principal),
                         db: Session = Depends(get_database_session)) -> dict[str, Any]:
    """Build state, error code and the tail of the build log of one version (poll while ``installing``)."""
    from nexus_platform.skills import install
    return install.status(db, principal, tenant_id, name, version)


@router.post("/tenants/{tenant_id}/skills/{name}/versions/{version}/reinstall")
def reinstall_skill(tenant_id: UUID, name: str, version: int,
                    sandbox_profile: str | None = Query(default=None, max_length=32),
                    principal: Principal = Depends(get_principal),
                    db: Session = Depends(get_database_session)) -> dict[str, Any]:
    """Build a version again from its stored zip (after a failure, or for another sandbox profile). Administrators."""
    from nexus_platform.skills import install
    return install.reinstall(db, principal, tenant_id, name, version, sandbox_profile)


@router.post("/tenants/{tenant_id}/skills/{name}/versions/{version}/stop-install")
def stop_skill_install(tenant_id: UUID, name: str, version: int, principal: Principal = Depends(get_principal),
                       db: Session = Depends(get_database_session)) -> dict[str, Any]:
    """Stop an install that is waiting or running. Administrators."""
    from nexus_platform.skills import install
    return install.stop(db, principal, tenant_id, name, version)


@router.get("/tenants/{tenant_id}/skills/{name}/bundle")
def download_skill(tenant_id: UUID, name: str, version: int | None = Query(default=None, ge=1),
                   principal: Principal = Depends(get_principal),
                   db: Session = Depends(get_database_session)) -> Response:
    """Download one skill version as a zip (the current version by default). Requires active membership."""
    skill, number, data = skills.export_bundle(db, principal, tenant_id, name, version)
    return Response(content=data, media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{skill}-v{number}.zip"'})


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
