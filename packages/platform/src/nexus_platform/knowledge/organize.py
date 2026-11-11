"""Organization of a knowledge base: tags, folders, custom metadata, pinning (openspec 2026-11-06-knowledge-base K5).

- Tags belong to one base; a document has any number of them (`tag_ids`), a FAQ entry one (`tag_id`).
  Deleting a tag removes it from its documents and entries (documents are never deleted with it).
- Folders are derived from `folder_path` (WeKnora: "folders are derived from the stored paths"): a path that does
  not exist yet is created by moving a document into it; renaming a folder rewrites the paths below it.
- Custom metadata is a flat string map per document that searches can filter on.
- Pinned bases are listed first.

All changes need write access to the base. Tags and folders only group documents: they never change who can read
them, and a search filter can narrow a search but never widen the Pre-Filter scope.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from nexus_core.platform import new_id, utc_now
from nexus_platform.authz.audit import audit
from nexus_platform.errors import Conflict, NotFound
from nexus_platform.persistence.models import (FaqEntryRecord, KnowledgeBaseRecord, KnowledgeDocumentRecord,
                                               KnowledgeTagRecord)
from . import access

MAX_TAGS = 200
MAX_DEPTH = 8
MAX_METADATA_KEYS = 30


# ---------------------------------------------------------------- tags

def tag_view(tag: KnowledgeTagRecord, count: int = 0) -> dict[str, Any]:
    # `seq_id` mirrors `id`: the copied pages key tags by it.
    return {'id': str(tag.id), 'seq_id': str(tag.id), 'name': tag.name, 'color': tag.color,
            'sort_order': tag.sort_order, 'knowledge_count': count, 'created_at': tag.created_at.isoformat()}


def _counts(db: Session, kb_id: UUID) -> dict[str, int]:
    counts: dict[str, int] = {}
    for tag_ids in db.scalars(select(KnowledgeDocumentRecord.tag_ids).where(
            KnowledgeDocumentRecord.kb_id == kb_id, KnowledgeDocumentRecord.status == 'active')):
        for tag_id in tag_ids or []:
            counts[tag_id] = counts.get(tag_id, 0) + 1
    for tag_id, count in db.execute(select(FaqEntryRecord.tag_id, func.count()).where(
            FaqEntryRecord.kb_id == kb_id, FaqEntryRecord.status == 'active', FaqEntryRecord.tag_id.is_not(None))
            .group_by(FaqEntryRecord.tag_id)):
        counts[str(tag_id)] = counts.get(str(tag_id), 0) + count
    return counts


def list_tags(db: Session, tenant_id: UUID, user_id: UUID, kb_id: UUID, keyword: str = '') -> list[dict[str, Any]]:
    kb = access.readable_base(db, kb_id, tenant_id, user_id)
    counts = _counts(db, kb.id)
    query = select(KnowledgeTagRecord).where(KnowledgeTagRecord.kb_id == kb.id)
    if keyword:
        query = query.where(KnowledgeTagRecord.name.ilike(f'%{keyword}%'))
    return [tag_view(t, counts.get(str(t.id), 0))
            for t in db.scalars(query.order_by(KnowledgeTagRecord.sort_order, KnowledgeTagRecord.name))]


def _clean_name(name: str) -> str:
    name = ' '.join((name or '').split())
    if not name or len(name) > 120:
        raise ValueError('tag name must be 1-120 characters')
    return name


def create_tag(db: Session, tenant_id: UUID, user_id: UUID, kb_id: UUID, *, name: str, color: str = '',
               sort_order: int = 0) -> KnowledgeTagRecord:
    kb = access.maintainable_base(db, kb_id, tenant_id, user_id)
    name = _clean_name(name)
    if db.scalar(select(func.count()).select_from(KnowledgeTagRecord).where(KnowledgeTagRecord.kb_id == kb.id)) >= MAX_TAGS:
        raise Conflict(f'at most {MAX_TAGS} tags per knowledge base')
    if db.scalar(select(KnowledgeTagRecord.id).where(KnowledgeTagRecord.kb_id == kb.id, KnowledgeTagRecord.name == name)):
        raise Conflict('A tag with this name already exists')
    tag = KnowledgeTagRecord(id=new_id(), tenant_id=kb.tenant_id, kb_id=kb.id, name=name, color=(color or '')[:32],
                             sort_order=int(sort_order), created_by=user_id, created_at=utc_now())
    db.add(tag)
    db.flush()
    audit(db, tenant_id, user_id, 'knowledge_tag.created', 'knowledge_base', str(kb.id), {'name': name})
    return tag


def _tag(db: Session, kb: KnowledgeBaseRecord, tag_id: UUID) -> KnowledgeTagRecord:
    tag = db.get(KnowledgeTagRecord, tag_id)
    if tag is None or tag.kb_id != kb.id:
        raise NotFound('Tag not found')
    return tag


def update_tag(db: Session, tenant_id: UUID, user_id: UUID, kb_id: UUID, tag_id: UUID, changes: Mapping[str, Any]
               ) -> KnowledgeTagRecord:
    kb = access.maintainable_base(db, kb_id, tenant_id, user_id)
    tag = _tag(db, kb, tag_id)
    if 'name' in changes and changes['name'] is not None:
        name = _clean_name(changes['name'])
        other = db.scalar(select(KnowledgeTagRecord.id).where(KnowledgeTagRecord.kb_id == kb.id,
                                                              KnowledgeTagRecord.name == name,
                                                              KnowledgeTagRecord.id != tag.id))
        if other:
            raise Conflict('A tag with this name already exists')
        tag.name = name
    if changes.get('color') is not None:
        tag.color = str(changes['color'])[:32]
    if changes.get('sort_order') is not None:
        tag.sort_order = int(changes['sort_order'])
    return tag


def delete_tag(db: Session, tenant_id: UUID, user_id: UUID, kb_id: UUID, tag_id: UUID, *, force: bool = False) -> int:
    """Delete a tag; without ``force`` a tag still in use is refused. Returns how many items lost the tag."""
    kb = access.maintainable_base(db, kb_id, tenant_id, user_id)
    tag = _tag(db, kb, tag_id)
    used = 0
    docs = [d for d in db.scalars(select(KnowledgeDocumentRecord).where(KnowledgeDocumentRecord.kb_id == kb.id))
            if str(tag.id) in (d.tag_ids or [])]
    entries = list(db.scalars(select(FaqEntryRecord).where(FaqEntryRecord.kb_id == kb.id, FaqEntryRecord.tag_id == tag.id)))
    used = len(docs) + len(entries)
    if used and not force:
        raise Conflict(f'Tag is used by {used} items; pass force to remove it from them')
    for doc in docs:
        doc.tag_ids = [t for t in doc.tag_ids if t != str(tag.id)]
    for entry in entries:
        entry.tag_id = None
    db.delete(tag)
    audit(db, tenant_id, user_id, 'knowledge_tag.deleted', 'knowledge_base', str(kb.id), {'name': tag.name, 'items': used})
    return used


# ---------------------------------------------------------------- documents

def clean_folder(path: str | None) -> str:
    parts = [p.strip() for p in (path or '').replace('\\', '/').split('/') if p.strip()]
    if any(p in ('.', '..') for p in parts) or len(parts) > MAX_DEPTH:
        raise ValueError(f'invalid folder path (no "." or "..", at most {MAX_DEPTH} levels)')
    folder = '/'.join(parts)
    if len(folder) > 1024:
        raise ValueError('folder path is too long')
    return folder


def clean_metadata(value: Mapping[str, Any] | None) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, Mapping) or len(value) > MAX_METADATA_KEYS:
        raise ValueError(f'metadata must be an object with at most {MAX_METADATA_KEYS} keys')
    return {str(k)[:64]: str(v)[:256] for k, v in value.items() if str(k).strip()}


def organize_documents(db: Session, tenant_id: UUID, user_id: UUID, kb_id: UUID, ids: Sequence[UUID],
                       changes: Mapping[str, Any]) -> int:
    """Set tags, folder and/or metadata on documents of the base. Only keys present in ``changes`` change."""
    kb = access.maintainable_base(db, kb_id, tenant_id, user_id)
    tags = None
    if 'tag_ids' in changes:
        wanted = [str(t) for t in changes['tag_ids'] or []]
        known = {str(i) for i in db.scalars(select(KnowledgeTagRecord.id).where(KnowledgeTagRecord.kb_id == kb.id))}
        if any(t not in known for t in wanted):
            raise NotFound('Tag not found')
        tags = list(dict.fromkeys(wanted))
    folder = clean_folder(changes['folder_path']) if 'folder_path' in changes else None
    metadata = clean_metadata(changes['custom_metadata']) if 'custom_metadata' in changes else None
    count = 0
    for doc in db.scalars(select(KnowledgeDocumentRecord).where(
            KnowledgeDocumentRecord.kb_id == kb.id, KnowledgeDocumentRecord.status == 'active',
            KnowledgeDocumentRecord.id.in_(list(ids)))):
        if tags is not None:
            doc.tag_ids = tags
        if folder is not None:
            doc.folder_path = folder
        if metadata is not None:
            doc.custom_metadata = metadata
        doc.updated_at = utc_now()
        count += 1
    audit(db, tenant_id, user_id, 'knowledge_document.organized', 'knowledge_base', str(kb.id), {'count': count})
    return count


def add_tags(db: Session, tenant_id: UUID, user_id: UUID, updates: Mapping[str, Sequence[str]]) -> int:
    """WeKnora batch tagging: ``{document_id: [tag_id...]}`` replaces each document's tags.

    The base of each document is looked up and its write access checked there; an unknown document is NotFound.
    """
    count = 0
    for doc_id, tag_ids in updates.items():
        doc = db.get(KnowledgeDocumentRecord, UUID(doc_id))
        if doc is None or doc.status != 'active':
            raise NotFound('Document not found')
        count += organize_documents(db, tenant_id, user_id, doc.kb_id, [doc.id], {'tag_ids': list(tag_ids)})
    return count


def folder_tree(db: Session, tenant_id: UUID, user_id: UUID, kb_id: UUID) -> dict[str, Any]:
    """Folders derived from document paths with direct and total counts (WeKnora ``KnowledgeFolderTree``)."""
    kb = access.readable_base(db, kb_id, tenant_id, user_id)
    direct: dict[str, int] = {}
    total = 0
    for path in db.scalars(select(KnowledgeDocumentRecord.folder_path).where(
            KnowledgeDocumentRecord.kb_id == kb.id, KnowledgeDocumentRecord.status == 'active')):
        direct[path or ''] = direct.get(path or '', 0) + 1
        total += 1
    nodes: dict[str, dict[str, Any]] = {}
    for path, count in direct.items():
        parts = path.split('/') if path else []
        for depth in range(1, len(parts) + 1):
            prefix = '/'.join(parts[:depth])
            node = nodes.setdefault(prefix, {'path': prefix, 'name': parts[depth - 1], 'document_count': 0,
                                             'total_count': 0, 'children': []})
            node['total_count'] += count
            if depth == len(parts):
                node['document_count'] += count
    roots: list[dict[str, Any]] = []
    for prefix in sorted(nodes):
        node = nodes[prefix]
        parent = nodes.get(prefix.rsplit('/', 1)[0]) if '/' in prefix else None
        (parent['children'] if parent else roots).append(node)
    return {'root_document_count': direct.get('', 0), 'total_document_count': total, 'folders': roots}


def rename_folder(db: Session, tenant_id: UUID, user_id: UUID, kb_id: UUID, source: str, target: str) -> int:
    """Rename or move a folder with everything below it."""
    kb = access.maintainable_base(db, kb_id, tenant_id, user_id)
    source, target = clean_folder(source), clean_folder(target)
    if not source:
        raise ValueError('the top level cannot be renamed')
    if target == source or target.startswith(source + '/'):
        raise ValueError('a folder cannot be moved into itself')
    count = 0
    for doc in db.scalars(select(KnowledgeDocumentRecord).where(KnowledgeDocumentRecord.kb_id == kb.id,
                                                                KnowledgeDocumentRecord.status == 'active')):
        if doc.folder_path == source or doc.folder_path.startswith(source + '/'):
            rest = doc.folder_path[len(source):]
            doc.folder_path = clean_folder(target + rest)
            doc.updated_at = utc_now()
            count += 1
    return count


def toggle_pin(db: Session, tenant_id: UUID, user_id: UUID, kb_id: UUID) -> bool:
    kb = access.manageable_base(db, kb_id, tenant_id, user_id)
    kb.pinned = not kb.pinned
    kb.pinned_at = utc_now() if kb.pinned else None
    return kb.pinned


# ---------------------------------------------------------------- search filters

@dataclass(frozen=True)
class DocumentFilter:
    """Narrows a search to documents (never widens it). Empty fields filter nothing."""

    tag_ids: tuple[str, ...] = ()
    folder: str | None = None
    recursive: bool = True
    metadata: Mapping[str, str] = field(default_factory=dict)

    def empty(self) -> bool:
        return not (self.tag_ids or self.folder is not None or self.metadata)

    def matches(self, doc: KnowledgeDocumentRecord) -> bool:
        if self.tag_ids and not set(self.tag_ids) & set(doc.tag_ids or []):
            return False
        if self.folder is not None:
            path = doc.folder_path or ''
            if not (path == self.folder or (self.recursive and (not self.folder or path.startswith(self.folder + '/')))):
                return False
        meta = doc.custom_metadata or {}
        return all(str(meta.get(k)) == str(v) for k, v in self.metadata.items())


def tag_ids_by_name(db: Session, kb_ids: Sequence[UUID], names: Sequence[str]) -> list[str]:
    """Tag ids (across the given bases) whose names match ``names`` case-insensitively."""
    wanted = {n.casefold() for n in names}
    return [str(t.id) for t in db.scalars(select(KnowledgeTagRecord).where(KnowledgeTagRecord.kb_id.in_(list(kb_ids))))
            if t.name.casefold() in wanted]
