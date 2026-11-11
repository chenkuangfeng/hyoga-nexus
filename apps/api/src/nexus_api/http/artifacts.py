"""Sandbox artifact endpoints (openspec 2026-11-07-tool-expansion 4.6, design 2.6).

Files a Run leaves under `/outputs` are registered when it ends. A person reaches the artifacts of their own sessions;
a space owner or admin reaches every artifact of the space. Downloads are attachments served as opaque bytes, so a
browser never renders an uploaded page or script. Rules live in `nexus_platform.artifacts.service`.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from nexus_core.deployment import DeploymentConfigError
from nexus_core.platform import Principal
from nexus_platform.artifacts import service
from nexus_platform.errors import NotFound
from nexus_api.dependencies.platform import get_database_session, get_principal

router = APIRouter(prefix='/api/v1/tenants/{tenant_id}/artifacts', tags=['Artifacts'])


def _root() -> Path:
    try:
        return service.artifacts_root()
    except DeploymentConfigError:
        raise NotFound('Artifacts are not available') from None


@router.get('')
def list_artifacts(tenant_id: UUID, session_id: UUID | None = None, run_id: UUID | None = None,
                   q: str = Query('', max_length=200), extensions: str = Query('', max_length=400),
                   latest: bool = False, limit: int = Query(50, ge=1, le=service.LIST_MAX), offset: int = Query(0, ge=0),
                   principal: Principal = Depends(get_principal), db: Session = Depends(get_database_session)) -> dict[str, Any]:
    """Artifacts the caller may see, newest first, with the total. Filter by session, Run, file name (`q`) and a
    comma-separated list of extensions; `latest` keeps only the newest version of each file of a session."""
    return service.search_artifacts(db, principal, tenant_id, session_id=session_id, run_id=run_id, q=q,
                                    extensions=[e.strip() for e in extensions.split(',') if e.strip()], latest=latest,
                                    limit=limit, offset=offset)


@router.get('/{artifact_id}')
def get_artifact(tenant_id: UUID, artifact_id: UUID, principal: Principal = Depends(get_principal),
                 db: Session = Depends(get_database_session)) -> dict[str, Any]:
    return service.get_artifact(db, principal, tenant_id, artifact_id)


@router.get('/{artifact_id}/download')
def download_artifact(tenant_id: UUID, artifact_id: UUID, principal: Principal = Depends(get_principal),
                      db: Session = Depends(get_database_session)) -> FileResponse:
    """The stored copy as an attachment. The download is audited."""
    view, path = service.open_artifact(db, principal, tenant_id, artifact_id, _root())
    return FileResponse(path, media_type='application/octet-stream', filename=view['name'],
                        headers={'X-Content-Type-Options': 'nosniff', 'Cache-Control': 'private, no-store'})


@router.delete('/{artifact_id}', status_code=204)
def delete_artifact(tenant_id: UUID, artifact_id: UUID, all_versions: bool = False,
                    principal: Principal = Depends(get_principal), db: Session = Depends(get_database_session)) -> Response:
    """Delete an artifact; with `all_versions` also every earlier registration of the same file in its session."""
    service.delete_artifact(db, principal, tenant_id, artifact_id, _root(), all_versions=all_versions)
    return Response(status_code=204)
