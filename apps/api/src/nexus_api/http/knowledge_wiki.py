"""Wiki knowledge base HTTP API (openspec 2026-11-06-knowledge-base K6).

Routes under ``/api/v1/tenants/{tenant_id}/knowledge/bases/{kb_id}/wiki``. Wiki slugs are hierarchical
(``entity/acme``), so page routes take the slug as a path. A stale ``version`` on a page update answers 409
(``conflict``) so editors can reload; reads need read access to the base, every change needs write access.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from nexus_api.dependencies.platform import get_database_session, get_principal
from nexus_core.platform import Principal
from nexus_platform.identity.service import require_membership, resolve_user
from nexus_platform.knowledge import wiki as service

router = APIRouter(prefix='/api/v1/tenants/{tenant_id}/knowledge/bases/{kb_id}/wiki', tags=['Knowledge Wiki'])


def _user(db: Session, principal: Principal, tenant_id: UUID):
    user = resolve_user(db, principal)
    require_membership(db, tenant_id, user.id)
    return user


class PageInput(BaseModel):
    slug: str | None = Field(None, max_length=200)
    title: str | None = Field(None, max_length=300)
    content: str | None = None
    summary: str | None = Field(None, max_length=2000)
    page_type: str | None = Field(None, max_length=16)
    status: str | None = Field(None, max_length=16)
    aliases: list[str] | None = Field(None, max_length=40)
    category_path: list[str] | None = Field(None, max_length=4)
    version: int | None = None


class FolderInput(BaseModel):
    parent_id: str = ''
    name: str | None = Field(None, max_length=120)
    move_parent: bool = False


class MoveInput(BaseModel):
    slug: str
    folder_id: str = ''


class RevertInput(BaseModel):
    slug: str
    version: int


class IssueStatusInput(BaseModel):
    status: str


@router.get('/pages')
def list_pages(tenant_id: UUID, kb_id: UUID, page_type: str = '', status: str = '', query: str = Query('', max_length=200),
               category_path: str = '', category_depth: int = 0, page: int = 1, page_size: int = 20,
               sort_by: str = 'updated_at', sort_order: str = 'desc', principal: Principal = Depends(get_principal),
               db: Session = Depends(get_database_session)):
    user = _user(db, principal, tenant_id)
    return service.list_pages(db, tenant_id, user.id, kb_id, page_type=page_type, status=status, query=query,
                              category_path=category_path, category_depth=category_depth, page=page,
                              page_size=page_size, sort_by=sort_by, sort_order=sort_order)


@router.post('/pages', status_code=201)
def create_page(tenant_id: UUID, kb_id: UUID, body: PageInput, principal: Principal = Depends(get_principal),
                db: Session = Depends(get_database_session)):
    with db.begin():
        user = _user(db, principal, tenant_id)
        return service.create_page(db, tenant_id, user.id, kb_id, body.model_dump())


@router.get('/pages/{slug:path}')
def get_page(tenant_id: UUID, kb_id: UUID, slug: str, principal: Principal = Depends(get_principal),
             db: Session = Depends(get_database_session)):
    user = _user(db, principal, tenant_id)
    return service.get_page(db, tenant_id, user.id, kb_id, slug)


@router.put('/pages/{slug:path}')
def update_page(tenant_id: UUID, kb_id: UUID, slug: str, body: PageInput, principal: Principal = Depends(get_principal),
                db: Session = Depends(get_database_session)):
    try:
        with db.begin():
            user = _user(db, principal, tenant_id)
            return service.update_page(db, tenant_id, user.id, kb_id, slug, body.model_dump(exclude_unset=True))
    except service.VersionConflict as exc:  # editors compare against current_version and offer an overwrite
        return JSONResponse(status_code=409, content={
            'error': {'code': 'conflict', 'message': str(exc)}, 'current_version': exc.current_version})


@router.delete('/pages/{slug:path}', status_code=204)
def delete_page(tenant_id: UUID, kb_id: UUID, slug: str, principal: Principal = Depends(get_principal),
                db: Session = Depends(get_database_session)):
    with db.begin():
        user = _user(db, principal, tenant_id)
        service.delete_page(db, tenant_id, user.id, kb_id, slug)


@router.get('/revisions/{slug:path}')
def revisions(tenant_id: UUID, kb_id: UUID, slug: str, version: int | None = None, limit: int = 50, offset: int = 0,
              principal: Principal = Depends(get_principal), db: Session = Depends(get_database_session)):
    user = _user(db, principal, tenant_id)
    if version is not None:
        return service.get_revision(db, tenant_id, user.id, kb_id, slug, version)
    return service.list_revisions(db, tenant_id, user.id, kb_id, slug, limit=limit, offset=offset)


@router.post('/revert')
def revert(tenant_id: UUID, kb_id: UUID, body: RevertInput, principal: Principal = Depends(get_principal),
           db: Session = Depends(get_database_session)):
    with db.begin():
        user = _user(db, principal, tenant_id)
        return service.revert_page(db, tenant_id, user.id, kb_id, body.slug, body.version)


@router.get('/folders')
def list_folders(tenant_id: UUID, kb_id: UUID, parent_id: str = '', page_types: str = '',
                 principal: Principal = Depends(get_principal), db: Session = Depends(get_database_session)):
    user = _user(db, principal, tenant_id)
    return service.list_folders(db, tenant_id, user.id, kb_id, parent_id, page_types)


@router.post('/folders', status_code=201)
def create_folder(tenant_id: UUID, kb_id: UUID, body: FolderInput, principal: Principal = Depends(get_principal),
                  db: Session = Depends(get_database_session)):
    with db.begin():
        user = _user(db, principal, tenant_id)
        return service.create_folder(db, tenant_id, user.id, kb_id, body.parent_id, body.name or '')


@router.put('/folders/{folder_id}')
def update_folder(tenant_id: UUID, kb_id: UUID, folder_id: UUID, body: FolderInput,
                  principal: Principal = Depends(get_principal), db: Session = Depends(get_database_session)):
    with db.begin():
        user = _user(db, principal, tenant_id)
        return service.update_folder(db, tenant_id, user.id, kb_id, folder_id, body.model_dump())


@router.delete('/folders/{folder_id}', status_code=204)
def delete_folder(tenant_id: UUID, kb_id: UUID, folder_id: UUID, principal: Principal = Depends(get_principal),
                  db: Session = Depends(get_database_session)):
    with db.begin():
        user = _user(db, principal, tenant_id)
        service.delete_folder(db, tenant_id, user.id, kb_id, folder_id)


@router.put('/move-page')
def move_page(tenant_id: UUID, kb_id: UUID, body: MoveInput, principal: Principal = Depends(get_principal),
              db: Session = Depends(get_database_session)):
    with db.begin():
        user = _user(db, principal, tenant_id)
        return service.move_page(db, tenant_id, user.id, kb_id, body.slug, body.folder_id)


@router.get('/index')
def wiki_index(tenant_id: UUID, kb_id: UUID, types: str = '', limit: int = 200, cursor: str = '',
               principal: Principal = Depends(get_principal), db: Session = Depends(get_database_session)):
    user = _user(db, principal, tenant_id)
    return service.get_index(db, tenant_id, user.id, kb_id, types=[t for t in types.split(',') if t], limit=limit,
                             cursor=cursor)


@router.get('/graph')
def wiki_graph(tenant_id: UUID, kb_id: UUID, mode: str = 'overview', center: str = '', depth: int = 1, types: str = '',
               limit: int = 500, principal: Principal = Depends(get_principal),
               db: Session = Depends(get_database_session)):
    user = _user(db, principal, tenant_id)
    return service.get_graph(db, tenant_id, user.id, kb_id, mode=mode, center=center, depth=depth,
                             types=[t for t in types.split(',') if t], limit=limit)


@router.get('/stats')
def wiki_stats(tenant_id: UUID, kb_id: UUID, principal: Principal = Depends(get_principal),
               db: Session = Depends(get_database_session)):
    user = _user(db, principal, tenant_id)
    return service.get_stats(db, tenant_id, user.id, kb_id)


@router.get('/search')
def wiki_search(tenant_id: UUID, kb_id: UUID, q: str = Query('', max_length=200), limit: int = 20,
                principal: Principal = Depends(get_principal), db: Session = Depends(get_database_session)):
    user = _user(db, principal, tenant_id)
    return service.search_pages(db, tenant_id, user.id, kb_id, q, limit)


@router.get('/issues')
def issues(tenant_id: UUID, kb_id: UUID, slug: str = '', status: str = '', principal: Principal = Depends(get_principal),
           db: Session = Depends(get_database_session)) -> list[dict[str, Any]]:
    user = _user(db, principal, tenant_id)
    return service.list_issues(db, tenant_id, user.id, kb_id, slug, status)


@router.put('/issues/{issue_id}/status')
def issue_status(tenant_id: UUID, kb_id: UUID, issue_id: UUID, body: IssueStatusInput,
                 principal: Principal = Depends(get_principal), db: Session = Depends(get_database_session)):
    with db.begin():
        user = _user(db, principal, tenant_id)
        return service.set_issue_status(db, tenant_id, user.id, kb_id, issue_id, body.status)


@router.post('/lint')
def lint(tenant_id: UUID, kb_id: UUID, principal: Principal = Depends(get_principal),
         db: Session = Depends(get_database_session)):
    with db.begin():
        user = _user(db, principal, tenant_id)
        return service.lint(db, tenant_id, user.id, kb_id)


@router.post('/rebuild-links')
def rebuild_links(tenant_id: UUID, kb_id: UUID, principal: Principal = Depends(get_principal),
                  db: Session = Depends(get_database_session)):
    with db.begin():
        user = _user(db, principal, tenant_id)
        return service.rebuild_links(db, tenant_id, user.id, kb_id)
