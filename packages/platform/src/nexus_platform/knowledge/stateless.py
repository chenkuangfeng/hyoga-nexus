"""Stateless knowledge retrieval for outbound MCP endpoints (openspec 2026-11-08-mcp, 2.4).

The Run-side tools in :mod:`nexus_platform.knowledge.tools` resolve scope from the Run's agent version and
number passages with the Run's evidence registry so citations can be resolved at the end of the Run. An MCP
endpoint has no Run, so this module serves the same Pre-Filter and content from an explicit scope
``(tenant_id, user_id, bound bases)`` and numbers each call's passages with a fresh registry: handles are
consistent within one call but never resolved against a Run answer.
"""
from __future__ import annotations

from typing import Any, Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from nexus_knowledge.evidence import EvidenceRegistry
from nexus_platform.persistence.models import (KnowledgeBaseRecord, KnowledgeChunkRecord, KnowledgeDocumentRecord,
                                               KnowledgeDocumentVersionRecord, WikiPageRecord)
from . import access, organize, search
from .tools import (_FENCE_NOTE, _degraded_note, _documents, _passage, _path, _position, _render_graph, _snippet)


def bound_ids(kb_ids: Sequence[str] | None) -> list[UUID] | None:
    """Endpoint KB scope as UUIDs; an empty scope means every readable base (``None``), never an empty list."""
    out: list[UUID] = []
    for value in kb_ids or []:
        try:
            out.append(UUID(str(value)))
        except (ValueError, AttributeError):
            continue
    return out or None


def _readable(db: Session, tenant_id: UUID, user_id: UUID, bound: Sequence[UUID] | None) -> list[KnowledgeBaseRecord]:
    return access.readable_bases(db, tenant_id, user_id, list(bound) if bound is not None else None)


async def search_knowledge(factory: sessionmaker[Session], db: Session, tenant_id: UUID, user_id: UUID,
                           bound: Sequence[UUID] | None, query: str, kb_ids: Sequence[str], limit: int,
                           filters: dict | None = None) -> str:
    """Pre-Filtered search over the endpoint's readable bases, with a per-call ``kb_ids`` subset."""
    requested = []
    for value in kb_ids or []:
        try:
            requested.append(UUID(str(value)))
        except ValueError:
            continue
    doc_filter = None
    filters = filters or {}
    if filters.get('tags') or filters.get('folder') is not None or filters.get('metadata'):
        tag_ids: list[str] = []
        if filters.get('tags'):
            tag_ids = organize.tag_ids_by_name(db, [kb.id for kb in _readable(db, tenant_id, user_id, bound)],
                                               filters['tags'])
            if not tag_ids:
                return 'No tag with these names exists in the readable knowledge bases.'
        doc_filter = organize.DocumentFilter(
            tuple(tag_ids), organize.clean_folder(filters['folder']) if filters.get('folder') is not None else None,
            True, {str(k): str(v) for k, v in (filters.get('metadata') or {}).items()})
    result = await search.search(factory, db, tenant_id, user_id, query, limit=limit, bound=bound,
                                 requested=requested or None, doc_filter=doc_filter)
    db.commit()
    registry = EvidenceRegistry()
    if not result.hits:
        return 'No relevant passages found in the readable knowledge bases.' + _degraded_note(result)
    body = '\n\n'.join(_passage(registry, hit.chunk_id, hit.content, hit.ref()) for hit in result.hits)
    return (f'<knowledge_results>\n{_FENCE_NOTE}\n{body}\n</knowledge_results>\n'
            'Cite a passage by ending the sentence that uses it with its [ID:n].' + _degraded_note(result))


async def read_document(factory: sessionmaker[Session], db: Session, tenant_id: UUID, user_id: UUID,
                        bound: Sequence[UUID] | None, document_id: str, start: int, count: int,
                        section: str | None = None) -> str:
    """Read consecutive chunks (or a section) of a readable document, numbered with a fresh registry."""
    try:
        doc_uuid = UUID(document_id)
    except ValueError:
        return 'Document not found.'
    readable = {kb.id for kb in _readable(db, tenant_id, user_id, bound)}
    doc = db.get(KnowledgeDocumentRecord, doc_uuid)
    if doc is None:
        wiki_page = db.get(WikiPageRecord, doc_uuid)  # a Wiki search hit names its page id as document_id
        if wiki_page is not None and wiki_page.status == 'published' and wiki_page.kb_id in readable:
            kb = db.get(KnowledgeBaseRecord, wiki_page.kb_id)
            if kb is not None:
                links = ', '.join(wiki_page.out_links or [])
                ref = {'kb_id': str(kb.id), 'document_id': str(wiki_page.id), 'version_id': str(wiki_page.id),
                       'filename': f'Wiki · {wiki_page.title}', 'page': None,
                       'section': list(wiki_page.category_path or []), 'ordinal': 0}
                text = f'# {wiki_page.title} ({wiki_page.slug})\n{wiki_page.content}' \
                       + (f'\n\nLinks: {links}' if links else '')
                body = _passage(EvidenceRegistry(), f'w:{wiki_page.id}', text, ref)
                return f'<knowledge_document chunks="1">\n{_FENCE_NOTE}\n{body}\n</knowledge_document>'
        return 'Document not found.'
    if doc.status != 'active' or doc.kb_id not in readable or doc.current_version_id is None:
        return 'Document not found.'
    version = db.get(KnowledgeDocumentVersionRecord, doc.current_version_id)
    query = select(KnowledgeChunkRecord).where(KnowledgeChunkRecord.version_id == doc.current_version_id,
                                               KnowledgeChunkRecord.parent_id.is_(None))
    if section:
        wanted = _path(section)
        rows_all = db.scalars(query.order_by(KnowledgeChunkRecord.ordinal)).all()
        chunks = [c for c in rows_all if list(c.section)[:len(wanted)] == wanted][:max(1, min(count, 10))]
        if not chunks:
            return f'No section "{section}" in this document; call document_outline to see its headings.'
    else:
        chunks = db.scalars(query.where(KnowledgeChunkRecord.ordinal >= max(0, start))
                            .order_by(KnowledgeChunkRecord.ordinal).limit(max(1, min(count, 10)))).all()
    total = version.chunk_count if version else 0
    rows = [(str(c.id), c.content, {'kb_id': str(doc.kb_id), 'document_id': str(doc.id),
                                    'version_id': str(doc.current_version_id), 'filename': doc.filename,
                                    'page': c.page, 'section': list(c.section), 'ordinal': c.ordinal}) for c in chunks]
    if not rows:
        return f'No chunk at {start}; the document has {total} chunks (0-{max(total - 1, 0)}).'
    registry = EvidenceRegistry()
    body = '\n\n'.join(_passage(registry, chunk_id, content, ref) for chunk_id, content, ref in rows)
    last = rows[-1][2]['ordinal']
    more = f'\nMore: read_document with chunk={last + 1}.' if last + 1 < total else ''
    return f'<knowledge_document chunks="{total}">\n{_FENCE_NOTE}\n{body}\n</knowledge_document>{more}'


async def list_documents(factory: sessionmaker[Session], db: Session, tenant_id: UUID, user_id: UUID,
                         bound: Sequence[UUID] | None, kb_id: str | None, keyword: str, offset: int,
                         limit: int) -> str:
    """List documents of the readable bases, optionally filtered by one base or a filename keyword."""
    wanted = list(bound) if bound is not None else None
    if kb_id:
        try:
            single = UUID(kb_id)
        except ValueError:
            return 'Knowledge base not found.'
        wanted = [single] if wanted is None else [i for i in wanted if i == single]
    bases = access.readable_bases(db, tenant_id, user_id, wanted)
    if not bases:
        return 'No readable knowledge base is in this endpoint\'s scope.'
    lines = []
    for kb in bases:
        rows, total = _documents(db, kb.id, keyword, offset, limit)
        lines.append(f'## {kb.name} (id {kb.id}) — {total} documents')
        lines += [f'- {doc.filename} | document_id={doc.id} | chunks={chunks} | updated {doc.updated_at:%Y-%m-%d}'
                  + (f' | {summary[:120]}' if summary else '') for doc, chunks, summary in rows]
    return '\n'.join(lines)


async def grep_chunks(factory: sessionmaker[Session], db: Session, tenant_id: UUID, user_id: UUID,
                      bound: Sequence[UUID] | None, pattern: str, kb_id: str | None, document_id: str | None,
                      ignore_case: bool, limit: int) -> str:
    """Exact-text search over the current chunks of readable documents (document order, no ranking)."""
    needle = pattern.strip()
    if not needle:
        return 'The pattern is empty.'
    requested = None
    if kb_id:
        try:
            requested = [UUID(kb_id)]
        except ValueError:
            return 'Knowledge base not found.'
    scoped, _ = search.resolve_scope(db, tenant_id, user_id, bound=bound, requested=requested)
    allowed = {v for item in scoped if item.kb.kb_type != 'faq' for v in item.version_ids}
    if not allowed:
        return 'No readable document is available in this endpoint\'s scope.'
    query = select(KnowledgeChunkRecord, KnowledgeDocumentRecord).join(
        KnowledgeDocumentVersionRecord, KnowledgeDocumentVersionRecord.id == KnowledgeChunkRecord.version_id).join(
        KnowledgeDocumentRecord, KnowledgeDocumentRecord.id == KnowledgeDocumentVersionRecord.document_id).where(
        KnowledgeChunkRecord.version_id.in_([UUID(v) for v in allowed]), KnowledgeChunkRecord.parent_id.is_(None))
    if document_id:
        try:
            query = query.where(KnowledgeDocumentRecord.id == UUID(document_id))
        except ValueError:
            return 'Document not found.'
    escaped = needle.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
    column = KnowledgeChunkRecord.content
    query = query.where(column.ilike(f'%{escaped}%', escape='\\') if ignore_case else column.like(f'%{escaped}%', escape='\\'))
    rows = db.execute(query.order_by(KnowledgeDocumentRecord.filename, KnowledgeChunkRecord.ordinal)
                      .limit(max(1, min(limit, 30)) + 1)).all()
    shown = rows[:max(1, min(limit, 30))]
    registry = EvidenceRegistry()
    lines = []
    for chunk, doc in shown:
        ref = {'kb_id': str(doc.kb_id), 'document_id': str(doc.id), 'version_id': str(chunk.version_id),
               'filename': doc.filename, 'page': chunk.page, 'section': list(chunk.section), 'ordinal': chunk.ordinal}
        handle = registry.stamp(str(chunk.id), ref)
        haystack = chunk.content.casefold() if ignore_case else chunk.content
        at = haystack.find(needle.casefold() if ignore_case else needle)
        lines.append(f'[ID:{handle}] {_position(ref)}\n{_snippet(chunk.content, max(at, 0), len(needle))}')
    if not shown:
        return f'No chunk contains "{needle}".'
    more = '\nMore matches exist; narrow the pattern or pass document_id.' if len(rows) > len(shown) else ''
    return f'<knowledge_matches>\n{_FENCE_NOTE}\n' + '\n\n'.join(lines) + f'\n</knowledge_matches>{more}'


async def document_outline(factory: sessionmaker[Session], db: Session, tenant_id: UUID, user_id: UUID,
                           bound: Sequence[UUID] | None, document_id: str) -> str:
    """Headings (or pages) of a readable document with chunk ranges."""
    try:
        doc_uuid = UUID(document_id)
    except ValueError:
        return 'Document not found.'
    readable = {kb.id for kb in _readable(db, tenant_id, user_id, bound)}
    doc = db.get(KnowledgeDocumentRecord, doc_uuid)
    if doc is None or doc.status != 'active' or doc.kb_id not in readable or doc.current_version_id is None:
        return 'Document not found.'
    rows = db.execute(select(KnowledgeChunkRecord.ordinal, KnowledgeChunkRecord.section, KnowledgeChunkRecord.page)
                      .where(KnowledgeChunkRecord.version_id == doc.current_version_id,
                             KnowledgeChunkRecord.parent_id.is_(None))
                      .order_by(KnowledgeChunkRecord.ordinal)).all()
    if not rows:
        return 'The document has no readable chunks.'
    entries: dict[tuple[str, ...], list[int]] = {}
    pages: dict[tuple[str, ...], set[int]] = {}
    for ordinal, section, page in rows:
        key = tuple(section or ())
        entries.setdefault(key, []).append(ordinal)
        if page:
            pages.setdefault(key, set()).add(page)
    if list(entries) == [()]:
        by_page = sorted({p for s in pages.values() for p in s})
        where = f'pages {by_page[0]}-{by_page[-1]}' if by_page else 'no headings'
        return f'《{doc.filename}》 has {len(rows)} chunks (0-{rows[-1][0]}) and {where}; read it with read_document(chunk=...).'
    lines = [f'《{doc.filename}》 — {len(rows)} chunks']
    for key, ordinals in entries.items():
        label = ' > '.join(key) if key else '(before the first heading)'
        page = f', pages {min(pages[key])}-{max(pages[key])}' if key in pages else ''
        lines.append(f'{"  " * max(len(key) - 1, 0)}- {label}: chunks {ordinals[0]}-{ordinals[-1]}{page}')
    lines.append('Read a section with read_document(document_id, section="<heading path>").')
    return '\n'.join(lines)


async def query_knowledge_graph(factory: sessionmaker[Session], db: Session, tenant_id: UUID, user_id: UUID,
                                bound: Sequence[UUID] | None, entities: list[str], kb_id: str | None,
                                hops: int) -> str:
    """Entities by exact name with their neighbourhood, from readable bases with a ready graph build."""
    from .graph import search as graph_search
    from nexus_knowledge.graph.retrieve import Limits
    requested = None
    if kb_id:
        try:
            requested = [UUID(kb_id)]
        except ValueError:
            return 'Knowledge base not found.'
    scoped, _ = search.resolve_scope(db, tenant_id, user_id, bound=bound, requested=requested)
    registry = EvidenceRegistry()
    results = []
    for item in scoped:
        build = graph_search.ready_build(db, item.kb.id) if item.kb.indexing.get('graph') and item.version_ids else None
        if build is None:
            continue
        found = await graph_search.lookup_entities(factory, db, item.kb, build, set(item.version_ids), entities,
                                                   Limits(hops=max(1, min(hops, 3))))
        if not found.empty():
            results.append((item.kb.name, found))
    text = _render_graph(db, results, registry) if results else ''
    return text or 'No matching entities in the knowledge graphs of the readable knowledge bases.'
