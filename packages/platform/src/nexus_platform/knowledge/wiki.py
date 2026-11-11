"""Wiki knowledge base pages, revisions, directory, graph and lint (openspec 2026-11-06-knowledge-base K6).

Ported from WeKnora ``wiki_page.go`` / ``wiki_lint.go``. A wiki base (``indexing.wiki``) keeps LLM-synthesized and
hand-written pages next to its normal documents. Every page write goes through :func:`write_page`, which

- snapshots the previous state as a revision and bumps ``version`` (the optimistic lock editors send back),
- re-derives ``out_links`` from the ``[[slug|name]]`` links of the content and ``in_links`` of the pages it links,
- marks the page ``index_state='pending'`` so the worker re-indexes it (a page is searchable only while
  ``published`` and ``ready``, see :mod:`wiki_ingest`).

Reading needs read access to the base, changing pages needs write access (:mod:`access`). The synthesis pipeline
lives in :mod:`wiki_ingest`.
"""
from __future__ import annotations

from collections import deque
from typing import Any, Iterable
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from nexus_core.platform import new_id, utc_now
from nexus_knowledge.wiki import rules
from nexus_platform.authz.audit import audit
from nexus_platform.errors import Conflict, NotFound
from nexus_platform.persistence.models import (KnowledgeBaseRecord, KnowledgeJobRecord, WikiFolderRecord, WikiIssueRecord, WikiPageRecord,
                                               WikiRevisionRecord)
from . import access

STATUSES = ('published', 'draft', 'archived')
MAX_CONTENT = 400_000
MAX_PAGES = 20_000
EDIT_SOURCES = ('pipeline', 'agent', 'user', 'revert')
#: Pages that are structure, not knowledge: excluded from the index listing, graph and issues.
SYSTEM_TYPES = ('index', 'log')


class VersionConflict(Conflict):
    """An editor saved on top of a page version that is no longer current (HTTP 409 with ``current_version``)."""

    def __init__(self, current_version: int) -> None:
        super().__init__(f'The page was changed by someone else (current version {current_version})')
        self.current_version = current_version


def wiki_enabled(kb: KnowledgeBaseRecord) -> bool:
    return bool((kb.indexing or {}).get('wiki'))


def _base(db: Session, tenant_id: UUID, user_id: UUID, kb_id: UUID, *, write: bool) -> KnowledgeBaseRecord:
    kb = (access.maintainable_base if write else access.readable_base)(db, kb_id, tenant_id, user_id)
    if not wiki_enabled(kb):
        raise NotFound('Wiki is not enabled for this knowledge base')
    return kb


def read_base(db, tenant_id, user_id, kb_id) -> KnowledgeBaseRecord:
    return _base(db, tenant_id, user_id, kb_id, write=False)


def write_base(db, tenant_id, user_id, kb_id) -> KnowledgeBaseRecord:
    return _base(db, tenant_id, user_id, kb_id, write=True)


# ---------------------------------------------------------------- views

def page_view(page: WikiPageRecord, *, content: bool = True, folder_path: str | None = None) -> dict[str, Any]:
    out = {
        'id': str(page.id), 'tenant_id': str(page.tenant_id), 'knowledge_base_id': str(page.kb_id), 'slug': page.slug,
        'title': page.title, 'page_type': page.page_type, 'status': page.status, 'summary': page.summary,
        'aliases': list(page.aliases or []), 'category_path': list(page.category_path or []),
        'wiki_path': folder_path if folder_path is not None else '/'.join(page.category_path or []),
        'depth': len(page.category_path or []), 'sort_order': page.sort_order, 'folder_id': str(page.folder_id or ''),
        'source_refs': list(page.source_refs or []), 'in_links': list(page.in_links or []),
        'out_links': list(page.out_links or []), 'page_metadata': dict(page.page_metadata or {}),
        'version': page.version, 'last_edit_source': page.last_edit_source,
        'last_editor_id': str(page.last_editor_id or ''), 'created_at': page.created_at.isoformat(),
        'updated_at': page.updated_at.isoformat()}
    out['content'] = page.content if content else ''
    return out


def revision_view(rev: WikiRevisionRecord, *, content: bool = False) -> dict[str, Any]:
    out = {'id': str(rev.id), 'tenant_id': str(rev.tenant_id), 'knowledge_base_id': str(rev.kb_id),
           'page_id': str(rev.page_id), 'slug': rev.slug, 'version': rev.version, 'title': rev.title,
           'page_type': rev.page_type, 'status': rev.status, 'summary': rev.summary, 'aliases': list(rev.aliases or []),
           'edit_source': rev.edit_source, 'editor_id': str(rev.editor_id or ''), 'edited_at': rev.edited_at.isoformat(),
           'created_at': rev.created_at.isoformat()}
    if content:
        out['content'] = rev.content
    return out


def folder_view(folder: WikiFolderRecord) -> dict[str, Any]:
    return {'id': str(folder.id), 'tenant_id': str(folder.tenant_id), 'knowledge_base_id': str(folder.kb_id),
            'parent_id': str(folder.parent_id or ''), 'name': folder.name, 'path': folder.path, 'depth': folder.depth,
            'sort_order': folder.sort_order, 'created_at': folder.created_at.isoformat(),
            'updated_at': folder.updated_at.isoformat()}


# ---------------------------------------------------------------- lookup

def find(db: Session, kb_id: UUID, slug: str) -> WikiPageRecord | None:
    page = db.scalar(select(WikiPageRecord).where(WikiPageRecord.kb_id == kb_id,
                                                  WikiPageRecord.slug == rules.normalize_slug(slug)))
    return page if page is not None and page.status != 'deleting' else None


def get_page(db: Session, tenant_id: UUID, user_id: UUID, kb_id: UUID, slug: str) -> dict[str, Any]:
    read_base(db, tenant_id, user_id, kb_id)
    page = find(db, kb_id, slug)
    if page is None:
        raise NotFound('Wiki page not found')
    view = page_view(page)
    titles = {}
    if page.in_links:
        titles = {p.slug: p.title for p in db.scalars(select(WikiPageRecord).where(
            WikiPageRecord.kb_id == kb_id, WikiPageRecord.slug.in_(list(page.in_links)),
            WikiPageRecord.status != 'deleting'))}
    view['in_link_titles'] = titles
    return view


def list_pages(db: Session, tenant_id: UUID, user_id: UUID, kb_id: UUID, *, page_type: str = '', status: str = '',
               query: str = '', category_path: str = '', category_depth: int = 0, page: int = 1, page_size: int = 20,
               sort_by: str = 'updated_at', sort_order: str = 'desc') -> dict[str, Any]:
    read_base(db, tenant_id, user_id, kb_id)
    where = [WikiPageRecord.kb_id == kb_id, WikiPageRecord.status != 'deleting']
    if page_type:
        where.append(WikiPageRecord.page_type.in_([t for t in page_type.split(',') if t]))
    if status:
        where.append(WikiPageRecord.status == status)
    if query.strip():
        like = f'%{query.strip()}%'
        where.append(or_(WikiPageRecord.title.ilike(like), WikiPageRecord.slug.ilike(like),
                         WikiPageRecord.summary.ilike(like)))
    rows = db.scalars(select(WikiPageRecord).where(*where)).all()
    if category_path:
        wanted = [p for p in category_path.split('/') if p]
        depth = category_depth or len(wanted)
        rows = [r for r in rows if list(r.category_path or [])[:depth] == wanted[:depth]]
    key = {'wiki_path': lambda r: ('/'.join(r.category_path or []).casefold(), r.title.casefold()), 'title': lambda r: r.title.casefold(), 'slug': lambda r: r.slug, 'created_at': lambda r: r.created_at,
           'sort_order': lambda r: (r.sort_order, r.title.casefold())}.get(sort_by, lambda r: r.updated_at)
    rows.sort(key=key, reverse=(sort_order != 'asc'))
    page_size = max(1, min(int(page_size or 20), 200))
    page = max(1, int(page or 1))
    chunk = rows[(page - 1) * page_size: page * page_size]
    return {'pages': [page_view(r, content=False) for r in chunk], 'total': len(rows), 'page': page,
            'page_size': page_size, 'total_pages': max(1, -(-len(rows) // page_size))}


# ---------------------------------------------------------------- writes

def _snapshot(db: Session, page: WikiPageRecord) -> None:
    db.add(WikiRevisionRecord(
        id=new_id(), tenant_id=page.tenant_id, kb_id=page.kb_id, page_id=page.id, slug=page.slug, version=page.version,
        title=page.title, page_type=page.page_type, status=page.status, content=page.content, summary=page.summary,
        aliases=list(page.aliases or []), edit_source=page.last_edit_source, editor_id=page.last_editor_id,
        edited_at=page.updated_at, created_at=utc_now()))


def _clean_aliases(aliases: Iterable[Any] | None, title: str) -> list[str]:
    return [a for a in dict.fromkeys(str(x).strip()[:160] for x in aliases or [] if str(x).strip())
            if a.casefold() != title.casefold()][:20]


def write_page(db: Session, kb: KnowledgeBaseRecord, page: WikiPageRecord | None, *, slug: str | None = None,
               source: str = 'user', editor_id: UUID | None = None, expected_version: int | None = None,
               **fields: Any) -> WikiPageRecord:
    """Create (``page`` None) or update a page; ``fields`` are title, page_type, status, content, summary, aliases,
    source_refs, category_path, folder_id, page_metadata. Raises :class:`Conflict` when ``expected_version`` is stale."""
    now = utc_now()
    if page is None:
        slug = rules.normalize_slug(slug or '')
        if not slug:
            raise ValueError('slug must not be empty')
        if find(db, kb.id, slug) is not None:
            raise Conflict('A wiki page with this slug already exists')
        if db.scalar(select(func.count()).select_from(WikiPageRecord).where(WikiPageRecord.kb_id == kb.id)) >= MAX_PAGES:
            raise ValueError(f'a wiki holds at most {MAX_PAGES} pages')
        page = WikiPageRecord(
            id=new_id(), tenant_id=kb.tenant_id, kb_id=kb.id, slug=slug, title='', page_type='concept',
            status='published', content='', summary='', aliases=[], category_path=[], sort_order=0, source_refs=[],
            in_links=[], out_links=[], page_metadata={}, version=0, last_edit_source=source, last_editor_id=editor_id,
            index_state='pending', index_attempts=0, created_at=now, updated_at=now)
        db.add(page)
    else:
        if expected_version is not None and expected_version != page.version:
            raise VersionConflict(page.version)
        _snapshot(db, page)
    title = str(fields.get('title', page.title) or '').strip()[:300]
    if not title:
        raise ValueError('title must not be empty')
    page_type = str(fields.get('page_type', page.page_type))
    if page_type not in rules.PAGE_TYPES:
        raise ValueError(f'page_type must be one of {", ".join(rules.PAGE_TYPES)}')
    status = str(fields.get('status', page.status))
    if status not in STATUSES:
        raise ValueError(f'status must be one of {", ".join(STATUSES)}')
    content = str(fields.get('content', page.content) or '')
    if len(content) > MAX_CONTENT:
        raise ValueError('content is too long')
    page.title, page.page_type, page.status, page.content = title, page_type, status, content
    page.summary = str(fields.get('summary', page.summary) or '')[:2000]
    page.aliases = _clean_aliases(fields.get('aliases', page.aliases), title)
    for name in ('source_refs', 'category_path', 'page_metadata'):
        if name in fields:
            setattr(page, name, fields[name])
    if 'folder_id' in fields:
        page.folder_id = fields['folder_id']
    page.out_links = [s for s in rules.extract_links(content) if s != page.slug]
    page.version += 1
    page.last_edit_source, page.last_editor_id = source, editor_id
    page.index_state, page.index_attempts, page.index_error = 'pending', 0, None
    page.updated_at = now
    db.flush()
    refresh_in_links(db, kb.id)
    return page


def refresh_in_links(db: Session, kb_id: UUID) -> None:
    """Re-derive every page's ``in_links`` from the stored ``out_links`` (only links to existing pages count)."""
    rows = db.execute(select(WikiPageRecord.id, WikiPageRecord.slug, WikiPageRecord.out_links, WikiPageRecord.in_links)
                      .where(WikiPageRecord.kb_id == kb_id, WikiPageRecord.status != 'deleting')).all()
    known = {slug for _, slug, _, _ in rows}
    incoming: dict[str, list[str]] = {slug: [] for slug in known}
    for _, slug, out_links, _ in rows:
        for target in out_links or []:
            if target in incoming and target != slug and slug not in incoming[target]:
                incoming[target].append(slug)
    for page_id, slug, _, current in rows:
        wanted = sorted(incoming[slug])
        if sorted(current or []) != wanted:
            db.get(WikiPageRecord, page_id).in_links = wanted


def rebuild_links(db: Session, tenant_id: UUID, user_id: UUID, kb_id: UUID) -> dict[str, Any]:
    """Re-parse every page's links (after imports or manual database changes)."""
    kb = write_base(db, tenant_id, user_id, kb_id)
    count = 0
    for page in db.scalars(select(WikiPageRecord).where(WikiPageRecord.kb_id == kb.id, WikiPageRecord.status != 'deleting')):
        page.out_links = [s for s in rules.extract_links(page.content) if s != page.slug]
        count += 1
    db.flush()
    refresh_in_links(db, kb.id)
    return {'pages': count}


def create_page(db: Session, tenant_id: UUID, user_id: UUID, kb_id: UUID, data: dict[str, Any]) -> dict[str, Any]:
    kb = write_base(db, tenant_id, user_id, kb_id)
    title = str(data.get('title') or '').strip()
    slug = data.get('slug') or title
    page_type = str(data.get('page_type') or 'concept')
    if page_type in rules.GENERATED_TYPES and '/' not in str(slug):
        slug = f'{page_type}/{slug}'
    category = rules.clean_category_path(data.get('category_path'))
    page = write_page(db, kb, None, slug=slug, source='user', editor_id=user_id, title=title, page_type=page_type,
                      status=str(data.get('status') or 'published'), content=str(data.get('content') or ''),
                      summary=str(data.get('summary') or ''), aliases=data.get('aliases'),
                      category_path=category, folder_id=ensure_folders(db, kb, category))
    audit(db, tenant_id, user_id, 'knowledge_wiki.page_created', access.KIND, str(kb.id), {'slug': page.slug})
    return page_view(page)


def update_page(db: Session, tenant_id: UUID, user_id: UUID, kb_id: UUID, slug: str, data: dict[str, Any]) -> dict[str, Any]:
    kb = write_base(db, tenant_id, user_id, kb_id)
    page = find(db, kb.id, slug)
    if page is None:
        raise NotFound('Wiki page not found')
    fields = {k: data[k] for k in ('title', 'content', 'summary', 'page_type', 'status', 'aliases') if data.get(k) is not None}
    version = data.get('version')
    page = write_page(db, kb, page, source='user', editor_id=user_id,
                      expected_version=int(version) if version is not None else None, **fields)
    audit(db, tenant_id, user_id, 'knowledge_wiki.page_updated', access.KIND, str(kb.id), {'slug': page.slug})
    return page_view(page)


def delete_page(db: Session, tenant_id: UUID, user_id: UUID, kb_id: UUID, slug: str) -> None:
    kb = write_base(db, tenant_id, user_id, kb_id)
    page = find(db, kb.id, slug)
    if page is None:
        raise NotFound('Wiki page not found')
    if page.page_type in SYSTEM_TYPES:
        raise ValueError('the index and log pages cannot be deleted')
    mark_deleting(db, page)
    refresh_in_links(db, kb.id)
    audit(db, tenant_id, user_id, 'knowledge_wiki.page_deleted', access.KIND, str(kb.id), {'slug': slug})


def mark_deleting(db: Session, page: WikiPageRecord) -> None:
    """Hide a page at once; the worker removes its index rows and then the row (revisions cascade)."""
    page.status, page.index_state, page.index_attempts = 'deleting', 'pending', 0
    page.in_links, page.out_links, page.updated_at = [], [], utc_now()


# ---------------------------------------------------------------- revisions

def list_revisions(db: Session, tenant_id: UUID, user_id: UUID, kb_id: UUID, slug: str, *, limit: int = 50,
                   offset: int = 0) -> dict[str, Any]:
    read_base(db, tenant_id, user_id, kb_id)
    page = find(db, kb_id, slug)
    if page is None:
        raise NotFound('Wiki page not found')
    total = db.scalar(select(func.count()).select_from(WikiRevisionRecord).where(WikiRevisionRecord.page_id == page.id))
    rows = db.scalars(select(WikiRevisionRecord).where(WikiRevisionRecord.page_id == page.id)
                      .order_by(WikiRevisionRecord.version.desc()).offset(max(0, offset)).limit(max(1, min(limit, 200))))
    return {'revisions': [revision_view(r) for r in rows], 'total': total, 'current_version': page.version}


def get_revision(db: Session, tenant_id: UUID, user_id: UUID, kb_id: UUID, slug: str, version: int) -> dict[str, Any]:
    read_base(db, tenant_id, user_id, kb_id)
    page = find(db, kb_id, slug)
    rev = db.scalar(select(WikiRevisionRecord).where(WikiRevisionRecord.page_id == page.id,
                                                     WikiRevisionRecord.version == version)) if page else None
    if rev is None:
        raise NotFound('Wiki revision not found')
    return revision_view(rev, content=True)


def revert_page(db: Session, tenant_id: UUID, user_id: UUID, kb_id: UUID, slug: str, version: int) -> dict[str, Any]:
    """Restore a revision as a regular edit: the current state is snapshotted, so a revert can be reverted."""
    kb = write_base(db, tenant_id, user_id, kb_id)
    page = find(db, kb.id, slug)
    rev = db.scalar(select(WikiRevisionRecord).where(WikiRevisionRecord.page_id == page.id,
                                                     WikiRevisionRecord.version == version)) if page else None
    if page is None or rev is None:
        raise NotFound('Wiki revision not found')
    page = write_page(db, kb, page, source='revert', editor_id=user_id, title=rev.title, page_type=rev.page_type,
                      status=rev.status if rev.status in STATUSES else 'published', content=rev.content,
                      summary=rev.summary, aliases=rev.aliases)
    audit(db, tenant_id, user_id, 'knowledge_wiki.page_reverted', access.KIND, str(kb.id),
          {'slug': page.slug, 'to_version': version})
    return page_view(page)


# ---------------------------------------------------------------- folders

def _folders(db: Session, kb_id: UUID) -> list[WikiFolderRecord]:
    return list(db.scalars(select(WikiFolderRecord).where(WikiFolderRecord.kb_id == kb_id)
                           .order_by(WikiFolderRecord.depth, WikiFolderRecord.sort_order, WikiFolderRecord.name)))


def _clean_name(name: str) -> str:
    cleaned = ' '.join(str(name or '').replace('/', ' ').replace('\\', ' ').split())[:120]
    if not cleaned:
        raise ValueError('folder name must not be empty')
    return cleaned


def ensure_folders(db: Session, kb: KnowledgeBaseRecord, labels: list[str]) -> UUID | None:
    """The folder at ``labels`` (created with its ancestors when missing); None for the root."""
    parent: WikiFolderRecord | None = None
    existing = {f.path: f for f in _folders(db, kb.id)}
    now = utc_now()
    for depth, label in enumerate(labels, start=1):
        path = f'{parent.path}/{label}' if parent else label
        folder = next((f for p, f in existing.items() if p.casefold() == path.casefold()), None)
        if folder is None:
            folder = WikiFolderRecord(id=new_id(), tenant_id=kb.tenant_id, kb_id=kb.id,
                                      parent_id=parent.id if parent else None, name=label, path=path, depth=depth,
                                      sort_order=0, created_at=now, updated_at=now)
            db.add(folder)
            db.flush()
            existing[path] = folder
        parent = folder
    return parent.id if parent else None


def folder_labels(folder: WikiFolderRecord | None) -> list[str]:
    return folder.path.split('/') if folder else []


def list_folders(db: Session, tenant_id: UUID, user_id: UUID, kb_id: UUID, parent_id: str = '',
                 page_types: str = '') -> dict[str, Any]:
    read_base(db, tenant_id, user_id, kb_id)
    types = {t for t in page_types.split(',') if t}
    folders = _folders(db, kb_id)
    pages = db.execute(select(WikiPageRecord.folder_id, WikiPageRecord.page_type).where(
        WikiPageRecord.kb_id == kb_id, WikiPageRecord.status != 'deleting')).all()
    by_id = {f.id: f for f in folders}
    counts: dict[UUID, int] = {}
    for folder_id, page_type in pages:
        if folder_id is None or (types and page_type not in types):
            continue
        node = by_id.get(folder_id)
        while node is not None:  # a folder counts its whole subtree
            counts[node.id] = counts.get(node.id, 0) + 1
            node = by_id.get(node.parent_id) if node.parent_id else None
    children = {f.id for f in folders if f.parent_id}
    wanted = UUID(parent_id) if parent_id else None
    nodes = []
    for folder in folders:
        if folder.parent_id != wanted:
            continue
        has_children = any(c.parent_id == folder.id for c in folders)
        if types and not counts.get(folder.id) and has_children:
            continue
        nodes.append({**folder_view(folder), 'page_count': counts.get(folder.id, 0), 'has_children': has_children})
    del children
    return {'parent_id': parent_id, 'folders': nodes}


def create_folder(db: Session, tenant_id: UUID, user_id: UUID, kb_id: UUID, parent_id: str, name: str) -> dict[str, Any]:
    kb = write_base(db, tenant_id, user_id, kb_id)
    parent = db.get(WikiFolderRecord, UUID(parent_id)) if parent_id else None
    if parent_id and (parent is None or parent.kb_id != kb.id):
        raise NotFound('Wiki folder not found')
    if parent is not None and parent.depth >= rules.MAX_CATEGORY_DEPTH + 2:
        raise ValueError('folders are nested at most four levels deep')
    name = _clean_name(name)
    path = f'{parent.path}/{name}' if parent else name
    if any(f.path.casefold() == path.casefold() for f in _folders(db, kb.id)):
        raise Conflict('A folder with this name already exists here')
    now = utc_now()
    folder = WikiFolderRecord(id=new_id(), tenant_id=kb.tenant_id, kb_id=kb.id, parent_id=parent.id if parent else None,
                              name=name, path=path, depth=(parent.depth + 1) if parent else 1, sort_order=0,
                              created_at=now, updated_at=now)
    db.add(folder)
    db.flush()
    return folder_view(folder)


def update_folder(db: Session, tenant_id: UUID, user_id: UUID, kb_id: UUID, folder_id: UUID, data: dict[str, Any]) -> dict[str, Any]:
    """Rename and/or move a folder; the paths of its subtree and the category path of its pages follow."""
    kb = write_base(db, tenant_id, user_id, kb_id)
    folder = db.get(WikiFolderRecord, folder_id)
    if folder is None or folder.kb_id != kb.id:
        raise NotFound('Wiki folder not found')
    folders = {f.id: f for f in _folders(db, kb.id)}
    name = _clean_name(data['name']) if data.get('name') else folder.name
    parent_id = folder.parent_id
    if data.get('move_parent'):
        parent_id = UUID(data['parent_id']) if data.get('parent_id') else None
        node = folders.get(parent_id) if parent_id else None
        while node is not None:
            if node.id == folder.id:
                raise ValueError('a folder cannot move into itself')
            node = folders.get(node.parent_id) if node.parent_id else None
        if parent_id and parent_id not in folders:
            raise NotFound('Wiki folder not found')
    parent = folders.get(parent_id) if parent_id else None
    new_path = f'{parent.path}/{name}' if parent else name
    if new_path != folder.path and any(f.path.casefold() == new_path.casefold() and f.id != folder.id for f in folders.values()):
        raise Conflict('A folder with this name already exists here')
    old_path = folder.path
    now = utc_now()
    for other in folders.values():
        if other.id == folder.id or other.path.startswith(old_path + '/'):
            other.path = new_path + other.path[len(old_path):]
            other.depth = other.path.count('/') + 1
            other.updated_at = now
    folder.name, folder.parent_id = name, parent_id
    db.flush()
    for page in db.scalars(select(WikiPageRecord).where(WikiPageRecord.kb_id == kb.id, WikiPageRecord.folder_id.is_not(None))):
        owner = folders.get(page.folder_id)
        if owner is not None:
            page.category_path = folder_labels(owner)
    return folder_view(folder)


def delete_folder(db: Session, tenant_id: UUID, user_id: UUID, kb_id: UUID, folder_id: UUID) -> None:
    kb = write_base(db, tenant_id, user_id, kb_id)
    folder = db.get(WikiFolderRecord, folder_id)
    if folder is None or folder.kb_id != kb.id:
        raise NotFound('Wiki folder not found')
    has_child = db.scalar(select(func.count()).select_from(WikiFolderRecord).where(WikiFolderRecord.parent_id == folder.id))
    has_page = db.scalar(select(func.count()).select_from(WikiPageRecord).where(
        WikiPageRecord.folder_id == folder.id, WikiPageRecord.status != 'deleting'))
    if has_child or has_page:
        raise Conflict('Only an empty folder can be deleted')
    db.delete(folder)


def move_page(db: Session, tenant_id: UUID, user_id: UUID, kb_id: UUID, slug: str, folder_id: str) -> dict[str, Any]:
    """File a page under a folder (``''`` = root). A move is not a content edit: no revision is made."""
    kb = write_base(db, tenant_id, user_id, kb_id)
    page = find(db, kb.id, slug)
    if page is None:
        raise NotFound('Wiki page not found')
    folder = db.get(WikiFolderRecord, UUID(folder_id)) if folder_id else None
    if folder_id and (folder is None or folder.kb_id != kb.id):
        raise NotFound('Wiki folder not found')
    page.folder_id, page.category_path, page.updated_at = (folder.id if folder else None), folder_labels(folder), utc_now()
    return page_view(page, content=False)


# ---------------------------------------------------------------- index, graph, stats, search

def get_index(db: Session, tenant_id: UUID, user_id: UUID, kb_id: UUID, *, types: list[str] | None = None,
              limit: int = 200, cursor: str = '') -> dict[str, Any]:
    read_base(db, tenant_id, user_id, kb_id)
    intro_page = find(db, kb_id, 'index')
    wanted = types or [t for t in rules.PAGE_TYPES if t not in SYSTEM_TYPES]
    offset = int(cursor) if cursor.isdigit() else 0
    groups = []
    for page_type in wanted:
        total = db.scalar(select(func.count()).select_from(WikiPageRecord).where(
            WikiPageRecord.kb_id == kb_id, WikiPageRecord.page_type == page_type, WikiPageRecord.status == 'published'))
        rows = db.scalars(select(WikiPageRecord).where(
            WikiPageRecord.kb_id == kb_id, WikiPageRecord.page_type == page_type, WikiPageRecord.status == 'published')
            .order_by(WikiPageRecord.title).offset(offset).limit(max(1, min(limit, 1000))))
        items = [{'slug': p.slug, 'title': p.title, 'summary': p.summary, 'category_path': list(p.category_path or []),
                  'wiki_path': '/'.join(p.category_path or []), 'depth': len(p.category_path or []),
                  'sort_order': p.sort_order} for p in rows]
        group = {'type': page_type, 'total': total, 'items': items}
        if offset + len(items) < total:
            group['next_cursor'] = str(offset + len(items))
        groups.append(group)
    return {'intro': intro_page.content if intro_page else '', 'version': intro_page.version if intro_page else 0,
            'groups': groups}


def get_graph(db: Session, tenant_id: UUID, user_id: UUID, kb_id: UUID, *, mode: str = 'overview', center: str = '',
              depth: int = 1, types: list[str] | None = None, limit: int = 500) -> dict[str, Any]:
    read_base(db, tenant_id, user_id, kb_id)
    pages = [p for p in db.scalars(select(WikiPageRecord).where(
        WikiPageRecord.kb_id == kb_id, WikiPageRecord.status == 'published')) if p.page_type not in SYSTEM_TYPES]
    if types:
        pages = [p for p in pages if p.page_type in types]
    by_slug = {p.slug: p for p in pages}
    edges = {(p.slug, t) for p in pages for t in p.out_links or [] if t in by_slug and t != p.slug}
    degree: dict[str, int] = {}
    for a, b in edges:
        degree[a] = degree.get(a, 0) + 1
        degree[b] = degree.get(b, 0) + 1
    limit = max(1, min(int(limit or 500), 2000))
    meta: dict[str, Any] = {'mode': mode, 'total': len(pages)}
    if mode == 'ego' and rules.normalize_slug(center) in by_slug:
        start = rules.normalize_slug(center)
        seen, queue = {start}, deque([(start, 0)])
        while queue:
            slug, d = queue.popleft()
            if d >= max(1, min(int(depth or 1), 4)):
                continue
            for a, b in edges:
                other = b if a == slug else a if b == slug else None
                if other and other not in seen:
                    seen.add(other)
                    queue.append((other, d + 1))
        chosen = sorted(seen, key=lambda s: (s != start, -degree.get(s, 0), s))[:limit]
        meta.update(center=start, depth=depth)
    else:
        meta['mode'] = 'overview'
        chosen = sorted(by_slug, key=lambda s: (-degree.get(s, 0), s))[:limit]
    keep = set(chosen)
    meta.update(returned=len(chosen), truncated=len(chosen) < len(pages) if mode != 'ego' else len(chosen) >= limit)
    return {'nodes': [{'slug': s, 'title': by_slug[s].title, 'page_type': by_slug[s].page_type,
                       'link_count': degree.get(s, 0)} for s in chosen],
            'edges': [{'source': a, 'target': b} for a, b in sorted(edges) if a in keep and b in keep], 'meta': meta}


def get_stats(db: Session, tenant_id: UUID, user_id: UUID, kb_id: UUID) -> dict[str, Any]:
    kb = read_base(db, tenant_id, user_id, kb_id)
    pages = db.scalars(select(WikiPageRecord).where(WikiPageRecord.kb_id == kb.id, WikiPageRecord.status != 'deleting')).all()
    content = [p for p in pages if p.page_type not in SYSTEM_TYPES]
    by_type: dict[str, int] = {}
    for p in pages:
        by_type[p.page_type] = by_type.get(p.page_type, 0) + 1
    pending = db.scalar(select(func.count()).select_from(KnowledgeJobRecord).where(
        KnowledgeJobRecord.kb_id == kb.id, KnowledgeJobRecord.kind == 'wiki', KnowledgeJobRecord.state == 'pending'))
    issues = db.scalar(select(func.count()).select_from(WikiIssueRecord).where(
        WikiIssueRecord.kb_id == kb.id, WikiIssueRecord.status == 'pending'))
    recent = sorted(pages, key=lambda p: p.updated_at, reverse=True)[:10]
    return {'total_pages': len(pages), 'pages_by_type': by_type, 'total_links': sum(len(p.out_links or []) for p in pages),
            'orphan_count': sum(1 for p in content if not p.in_links and not p.out_links),
            'recent_updates': [page_view(p, content=False) for p in recent], 'pending_tasks': pending,
            'pending_issues': issues, 'is_active': True}


def search_pages(db: Session, tenant_id: UUID, user_id: UUID, kb_id: UUID, q: str, limit: int = 20) -> dict[str, Any]:
    """Lexical page search for the browser (title, alias, summary, content); agents use the hybrid index instead."""
    read_base(db, tenant_id, user_id, kb_id)
    q = (q or '').strip()
    if not q:
        return {'pages': [], 'total': 0}
    like = f'%{q}%'
    rows = db.scalars(select(WikiPageRecord).where(
        WikiPageRecord.kb_id == kb_id, WikiPageRecord.status == 'published',
        or_(WikiPageRecord.title.ilike(like), WikiPageRecord.slug.ilike(like), WikiPageRecord.summary.ilike(like),
            WikiPageRecord.content.ilike(like))).limit(500)).all()

    def score(p: WikiPageRecord) -> int:
        low = q.casefold()
        return (4 if p.title.casefold() == low else 3 if low in p.title.casefold() else 2 if any(low in a.casefold() for a in p.aliases or []) else 1)
    rows = sorted(rows, key=lambda p: (-score(p), p.title))[:max(1, min(int(limit or 20), 100))]
    return {'pages': [page_view(p, content=False) for p in rows], 'total': len(rows)}


# ---------------------------------------------------------------- lint and issues

def lint(db: Session, tenant_id: UUID, user_id: UUID, kb_id: UUID) -> dict[str, Any]:
    """Report structural problems as ``pending`` issues: broken links, orphans and empty pages (WeKnora lint)."""
    kb = write_base(db, tenant_id, user_id, kb_id)
    pages = [p for p in db.scalars(select(WikiPageRecord).where(
        WikiPageRecord.kb_id == kb.id, WikiPageRecord.status != 'deleting')) if p.page_type not in SYSTEM_TYPES]
    known = {p.slug for p in db.scalars(select(WikiPageRecord).where(WikiPageRecord.kb_id == kb.id, WikiPageRecord.status != 'deleting'))}
    open_keys = {(i.slug, i.issue_type) for i in db.scalars(select(WikiIssueRecord).where(
        WikiIssueRecord.kb_id == kb.id, WikiIssueRecord.status == 'pending'))}
    found = []
    for p in pages:
        broken = [t for t in p.out_links or [] if t not in known]
        if broken:
            found.append((p, 'broken_link', 'Links to missing pages: ' + ', '.join(broken[:8])))
        if not p.in_links and not p.out_links:
            found.append((p, 'orphan', 'The page has no links to or from other pages'))
        if len(p.content.strip()) < 40:
            found.append((p, 'empty', 'The page has almost no content'))
    now, created = utc_now(), 0
    for page, issue_type, description in found:
        if (page.slug, issue_type) in open_keys:
            continue
        db.add(WikiIssueRecord(id=new_id(), tenant_id=kb.tenant_id, kb_id=kb.id, slug=page.slug, issue_type=issue_type,
                               description=description, suspected_knowledge_ids=list(page.source_refs or []),
                               status='pending', reported_by='lint', created_at=now, updated_at=now))
        created += 1
    db.flush()
    return {'checked': len(pages), 'new_issues': created}


def issue_view(issue: WikiIssueRecord) -> dict[str, Any]:
    return {'id': str(issue.id), 'tenant_id': str(issue.tenant_id), 'knowledge_base_id': str(issue.kb_id),
            'slug': issue.slug, 'issue_type': issue.issue_type, 'description': issue.description,
            'suspected_knowledge_ids': list(issue.suspected_knowledge_ids or []), 'status': issue.status,
            'reported_by': issue.reported_by, 'created_at': issue.created_at.isoformat(),
            'updated_at': issue.updated_at.isoformat()}


def list_issues(db: Session, tenant_id: UUID, user_id: UUID, kb_id: UUID, slug: str = '', status: str = '') -> list[dict[str, Any]]:
    read_base(db, tenant_id, user_id, kb_id)
    query = select(WikiIssueRecord).where(WikiIssueRecord.kb_id == kb_id)
    if slug:
        query = query.where(WikiIssueRecord.slug == rules.normalize_slug(slug))
    if status:
        query = query.where(WikiIssueRecord.status == status)
    return [issue_view(i) for i in db.scalars(query.order_by(WikiIssueRecord.created_at.desc()).limit(500))]


def set_issue_status(db: Session, tenant_id: UUID, user_id: UUID, kb_id: UUID, issue_id: UUID, status: str) -> dict[str, Any]:
    kb = write_base(db, tenant_id, user_id, kb_id)
    if status not in ('pending', 'resolved', 'ignored'):
        raise ValueError('status must be pending, resolved or ignored')
    issue = db.get(WikiIssueRecord, issue_id)
    if issue is None or issue.kb_id != kb.id:
        raise NotFound('Wiki issue not found')
    issue.status, issue.updated_at = status, utc_now()
    return issue_view(issue)
