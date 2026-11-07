"""Wiki synthesis from documents and page indexing (openspec 2026-11-06-knowledge-base K6).

Ported from WeKnora ``wiki_ingest*.go`` with its prompts (:mod:`nexus_knowledge.wiki.prompts`). When a document
version of a wiki base (``indexing.wiki``) becomes ``ready`` a ``wiki`` job runs :func:`ingest`:

1. a summary page ``summary/<document>`` is written (``SUMMARY:`` line + Markdown);
2. entities and concepts are extracted (granularity ``focused``/``standard``/``exhaustive``); each is compared with
   lexically similar existing pages and the model decides exact duplicates, which are merged into the existing page
   (the new name becomes an alias);
3. each page is written by the "compiler" prompt from the document excerpts that mention it; ``[[slug|name]]`` links
   to unknown slugs are removed, links to the page itself too;
4. new pages are filed into a directory tree by one taxonomy call that reuses existing folders;
5. pages this document produced earlier but no longer extracts lose the document as a source;
6. the ``index`` page gets (or updates) its introduction.

A ``wiki`` job without a version is a **retraction** of a deleted document: its summary page is deleted, pages whose
only source it was are deleted, other pages are rewritten without its contribution.

All model calls use the knowledge base creator's key (decision 6). Pages written here carry
``last_edit_source='pipeline'``; hand edits are never skipped, the model merges new facts into the current text.
:func:`index_tick` embeds changed pages and deletes removed ones, like FAQ entries; a page is searched through its
id as the index "version". The synthesis is idempotent per document: a retry converges on the same pages (slugs are
stable), at worst with a repeated merge call.
"""
from __future__ import annotations

import logging
import re
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from nexus_core.platform import new_id, utc_now
from nexus_knowledge.index import IndexRow, collection_name
from nexus_knowledge.text import tokenize
from nexus_knowledge.wiki import prompts, rules
from nexus_platform.persistence.models import (KnowledgeBaseRecord, KnowledgeChunkRecord, KnowledgeDocumentRecord,
                                               KnowledgeDocumentVersionRecord, KnowledgeJobRecord, WikiPageRecord)
from . import embedding, stores, wiki
from .graph import llm

logger = logging.getLogger(__name__)

DOC_CHARS = 30_000
EXCERPT_CHARS = 3_500
DEFAULT_MAX_PAGES = 30
INDEX_BATCH = 16
MAX_INDEX_ATTEMPTS = 4
ROW_CHARS = 700
MAX_ROWS = 12
DEFAULT_LANGUAGE = "the document's own language"


class WikiFailed(Exception):
    """Permanent failure (configuration): the job fails without retrying."""


def _uuid(value: Any) -> UUID | None:
    try:
        return UUID(str(value)) if value else None
    except ValueError:
        return None


def config_of(kb: KnowledgeBaseRecord) -> dict[str, Any]:
    """Normalized ``wiki_config``: model, granularity, per-document page cap and extra instructions."""
    raw = (kb.settings or {}).get('wiki_config') or {}
    granularity = raw.get('extraction_granularity')
    return {'model_id': _uuid(raw.get('synthesis_model_id')),
            'granularity': granularity if granularity in ('focused', 'exhaustive') else 'standard',
            'max_pages': int(raw.get('max_pages_per_ingest') or 0) or DEFAULT_MAX_PAGES,
            'content_instructions': str(raw.get('content_instructions') or '').strip()[:2000],
            'extraction_instructions': str(raw.get('extraction_instructions') or '').strip()[:2000],
            'language': str(raw.get('language') or '').strip() or DEFAULT_LANGUAGE}


def schedule(db: Session, kb: KnowledgeBaseRecord, version_id: UUID | None, document_id: UUID | None) -> None:
    """Queue a synthesis (ready ``version_id``) or a retraction (``version_id`` None) for a wiki base."""
    if not wiki.wiki_enabled(kb) or config_of(kb)['model_id'] is None:
        return
    if db.scalar(select(KnowledgeJobRecord.id).where(
            KnowledgeJobRecord.kb_id == kb.id, KnowledgeJobRecord.kind == 'wiki', KnowledgeJobRecord.state == 'pending',
            KnowledgeJobRecord.version_id == version_id, KnowledgeJobRecord.document_id == document_id)) is not None:
        return
    now = utc_now()
    db.add(KnowledgeJobRecord(id=new_id(), tenant_id=kb.tenant_id, kb_id=kb.id, document_id=document_id,
                              version_id=version_id, kind='wiki', state='pending', attempts=0, available_at=now,
                              created_at=now, updated_at=now))


def backfill(db: Session, kb: KnowledgeBaseRecord) -> int:
    """Queue synthesis for every ready document of a base that just got Wiki enabled (or a new model)."""
    count = 0
    for doc in db.scalars(select(KnowledgeDocumentRecord).where(
            KnowledgeDocumentRecord.kb_id == kb.id, KnowledgeDocumentRecord.status == 'active',
            KnowledgeDocumentRecord.current_version_id.is_not(None))):
        version = db.get(KnowledgeDocumentVersionRecord, doc.current_version_id)
        if version is not None and version.state == 'ready' and version.enrichment.get('wiki') != 'done':
            schedule(db, kb, version.id, doc.id)
            count += 1
    return count


async def run(factory: sessionmaker[Session], job_id: UUID) -> None:
    with factory() as db:
        job = db.get(KnowledgeJobRecord, job_id)
        kb = db.get(KnowledgeBaseRecord, job.kb_id) if job else None
        if job is None or kb is None or kb.status != 'active' or not wiki.wiki_enabled(kb):
            return
        if config_of(kb)['model_id'] is None:
            raise WikiFailed('the wiki has no synthesis model')
        kb_id, version_id, document_id = kb.id, job.version_id, job.document_id
    if version_id is not None:
        await ingest(factory, version_id)
    elif document_id is not None:
        await retract(factory, kb_id, document_id)


# ---------------------------------------------------------------- helpers

def _doc_text(db: Session, version_id: UUID) -> str:
    chunks = db.scalars(select(KnowledgeChunkRecord.content).where(
        KnowledgeChunkRecord.version_id == version_id, KnowledgeChunkRecord.parent_id.is_(None))
        .order_by(KnowledgeChunkRecord.ordinal))
    out, size = [], 0
    for text in chunks:
        out.append(text)
        size += len(text)
        if size >= DOC_CHARS:
            break
    return '\n\n'.join(out)[:DOC_CHARS]


def _excerpts(text: str, names: list[str]) -> str:
    """Paragraphs of the document that mention one of the names (verbatim source text for the page prompt)."""
    keys = [n.casefold() for n in names if n]
    picked, size = [], 0
    for paragraph in re.split(r'\n\s*\n', text):
        if keys and any(k in paragraph.casefold() for k in keys):
            picked.append(paragraph.strip())
            size += len(paragraph)
            if size >= EXCERPT_CHARS:
                break
    return '\n\n'.join(picked)[:EXCERPT_CHARS]


def doc_slug(filename: str, document_id: UUID) -> str:
    stem = filename.rsplit('.', 1)[0] if '.' in filename else filename
    return f'summary/{rules.normalize_slug(stem)[:80] or "doc"}-{str(document_id)[:8]}'


def _slug_lines(items: list[tuple[str, str, list[str]]]) -> str:
    lines = []
    for slug, name, aliases in items:
        extra = f' (Aliases: {", ".join(aliases)})' if aliases else ''
        lines.append(f'[[{slug}]] = {name}{extra}')
    return '\n'.join(lines) or '(none)'


async def _ask(factory, ids, model, system: str, user: str, tokens: int = 4000) -> str:
    return await llm.complete(factory, ids[0], ids[1], model, 'knowledge.wiki', system, user, tokens)


def _page_user_prompt(*, slug: str, title: str, page_type: str, aliases: list[str], existing: str, new_content: str,
                      deleted: str, remaining: str, valid: str, language: str, shared: str = '') -> str:
    return prompts.render_conditional(
        prompts.PAGE_MODIFY_USER_PROMPT, HasAdditions=bool(new_content), HasRetractions=bool(deleted),
        SharedSourceContexts=shared + '\n' if shared else '', PageSlug=slug, PageTitle=title, PageType=page_type,
        PageAliases=', '.join(aliases), ExistingContent=existing or '(new page)', NewContent=new_content,
        DeletedContent=deleted, RemainingSourcesContent=remaining, AvailableSlugs=valid, Language=language)


def _system(content_instructions: str) -> str:
    extra = f'\n\n### BUSINESS INSTRUCTIONS (lower priority than the rules above)\n{content_instructions}' if content_instructions else ''
    return prompts.PAGE_MODIFY_SYSTEM_PROMPT + extra


# ---------------------------------------------------------------- ingest

async def ingest(factory: sessionmaker[Session], version_id: UUID) -> None:
    with factory() as db:
        version = db.get(KnowledgeDocumentVersionRecord, version_id)
        doc = db.get(KnowledgeDocumentRecord, version.document_id) if version else None
        kb = db.get(KnowledgeBaseRecord, version.kb_id) if version else None
        if version is None or doc is None or kb is None or doc.status != 'active' or kb.status != 'active' \
                or version.state != 'ready' or doc.current_version_id != version.id or version.enrichment.get('wiki') == 'done':
            return
        config = config_of(kb)
        text = _doc_text(db, version_id)
        ids = (kb.tenant_id, kb.created_by)
        kb_id, doc_id, filename = kb.id, str(doc.id), doc.filename
        previous = [(p.slug, p.title) for p in db.scalars(select(WikiPageRecord).where(
            WikiPageRecord.kb_id == kb.id, WikiPageRecord.status != 'deleting', WikiPageRecord.page_type.in_(['entity', 'concept'])))
            if doc_id in (p.source_refs or [])]
    model, language = config['model_id'], config['language']
    if not text.strip():
        await retract_pages(factory, kb_id, doc_id, only_types=('entity', 'concept'))
        _mark_done(factory, version_id)
        return

    extract = prompts.render(prompts.KNOWLEDGE_EXTRACT_PROMPT, Content=text, Language=language,
                             PreviousSlugs='\n'.join(f'{s} ({t})' for s, t in previous) or '(none)')
    extract += f'\n\n### Extraction Scope (Granularity: {config["granularity"]})\n{prompts.granularity_guidance(config["granularity"])}'
    if config['extraction_instructions']:
        extract += f'\n\n### Business instructions\n{config["extraction_instructions"]}'
    items = rules.parse_extraction(await _ask(factory, ids, model, 'You extract knowledge for a wiki. Reply with JSON only.', extract, 4000),
                                   config['max_pages'])
    items = await _dedupe(factory, ids, model, kb_id, items)

    # Summary page (links to the extracted pages).
    summary_reply = await _ask(factory, ids, model, 'You are a careful wiki editor.', prompts.render(
        prompts.SUMMARY_PROMPT, Content=text, Language=language,
        ExtractedSlugs=_slug_lines([(i.slug, i.name, i.aliases) for i in items])), 4000)
    summary, body = rules.split_summary(summary_reply)
    summary_slug = doc_slug(filename, UUID(doc_id))
    _upsert(factory, kb_id, summary_slug, doc_id, title=filename.rsplit('.', 1)[0] or filename, page_type='summary',
            content=body or summary, summary=summary, aliases=[], extra_valid={i.slug for i in items})

    # Entity / concept pages.
    created: list[str] = []
    for item in items:
        with factory() as db:
            existing = wiki.find(db, kb_id, item.slug)
            current = (existing.content, existing.title, list(existing.aliases or [])) if existing else ('', item.name, item.aliases)
            valid = {p for p in db.scalars(select(WikiPageRecord.slug).where(
                WikiPageRecord.kb_id == kb_id, WikiPageRecord.status != 'deleting'))} | {i.slug for i in items} | {summary_slug}
        excerpt = _excerpts(text, [item.name, *item.aliases]) or item.details
        new_info = (f'{item.details}\n\n{excerpt}' if item.details and excerpt != item.details else excerpt)[:EXCERPT_CHARS + 800]
        user = _page_user_prompt(
            slug=item.slug, title=current[1], page_type=item.kind, aliases=current[2], existing=current[0],
            new_content=new_info, deleted='', remaining='', valid=_slug_lines([(s, s.split('/', 1)[-1], []) for s in sorted(valid - {item.slug})][:400]),
            language=language, shared=f'<source><type>document</type><summary>{summary}</summary></source>')
        reply = await _ask(factory, ids, model, _system(config['content_instructions']), user, 4000)
        page_summary, page_body = rules.split_summary(reply)
        if not page_body.strip():
            continue
        was_new = _upsert(factory, kb_id, item.slug, doc_id, title=current[1], page_type=item.kind, content=page_body,
                          summary=page_summary or item.description,
                          aliases=list(dict.fromkeys([*current[2], *item.aliases])), extra_valid=valid)
        if was_new:
            created.append(item.slug)

    await _file_pages(factory, ids, model, kb_id, created, language)
    kept = {i.slug for i in items}
    for slug, _ in previous:
        if slug not in kept:
            await retract_pages(factory, kb_id, doc_id, only_slugs={slug})
    await _refresh_index_page(factory, ids, model, kb_id, language, f'Added the document "{filename}".')
    _mark_done(factory, version_id)


def _mark_done(factory, version_id: UUID) -> None:
    with factory() as db, db.begin():
        row = db.get(KnowledgeDocumentVersionRecord, version_id)
        row.enrichment = {**row.enrichment, 'wiki': 'done'}
        row.updated_at = utc_now()


def _upsert(factory, kb_id: UUID, slug: str, doc_id: str, *, title: str, page_type: str, content: str, summary: str,
            aliases: list[str], extra_valid: set[str]) -> bool:
    """Write a pipeline page, adding ``doc_id`` to its sources; returns True when the page is new."""
    with factory() as db, db.begin():
        kb = db.get(KnowledgeBaseRecord, kb_id)
        page = wiki.find(db, kb_id, slug)
        known = set(db.scalars(select(WikiPageRecord.slug).where(
            WikiPageRecord.kb_id == kb_id, WikiPageRecord.status != 'deleting'))) | extra_valid
        sources = list(dict.fromkeys([*(page.source_refs if page else []), doc_id]))
        clean = rules.sanitize_links(content, known, slug)
        wiki.write_page(db, kb, page, slug=slug, source='pipeline', title=page.title if page and page.title else title,
                        page_type=page.page_type if page else page_type, content=clean, summary=summary,
                        aliases=aliases, source_refs=sources)
        return page is None


async def _dedupe(factory, ids, model, kb_id: UUID, items: list[rules.Extracted]) -> list[rules.Extracted]:
    """Merge items the model judges to be the same thing as an existing page (new name → alias)."""
    if not items:
        return items
    with factory() as db:
        existing = [(p.slug, p.title, list(p.aliases or [])) for p in db.scalars(select(WikiPageRecord).where(
            WikiPageRecord.kb_id == kb_id, WikiPageRecord.status != 'deleting', WikiPageRecord.page_type.in_(['entity', 'concept'])))]
    names = {slug: (title, aliases) for slug, title, aliases in existing}
    candidates = {i.slug: [s for s in rules.similar_pages(i, existing) if s != i.slug] for i in items if i.slug not in names}
    candidates = {k: v for k, v in candidates.items() if v}
    if not candidates:
        return items
    blocks = []
    for item in items:
        if item.slug in candidates:
            pages = ''.join(f'<page><slug>{s}</slug><name>{names[s][0]}</name>' + ''.join(f'<alias>{a}</alias>' for a in names[s][1])
                            + '</page>' for s in candidates[item.slug])
            blocks.append(f'<item><slug>{item.slug}</slug><name>{item.name}</name>'
                          + ''.join(f'<alias>{a}</alias>' for a in item.aliases)
                          + f'<description>{item.description}</description><candidates>{pages}</candidates></item>')
    reply = await _ask(factory, ids, model, 'You are a strict deduplication system. Reply with JSON only.',
                       prompts.render(prompts.DEDUPLICATION_PROMPT, Candidates='\n'.join(blocks)), 1500)
    merges = rules.parse_merges(reply, set(candidates), {k: set(v) for k, v in candidates.items()})
    out: dict[str, rules.Extracted] = {}
    for item in items:
        target = merges.get(item.slug)
        if target:
            item = rules.Extracted(item.kind, names[target][0], target,
                                   list(dict.fromkeys([item.name, *item.aliases])), item.description, item.details)
        out.setdefault(item.slug, item)
    return list(out.values())


async def _file_pages(factory, ids, model, kb_id: UUID, slugs: list[str], language: str) -> None:
    """Assign directory paths to new pages in one call that reuses the existing folders."""
    if not slugs:
        return
    with factory() as db:
        folders = [f.path for f in wiki._folders(db, kb_id)]
        rows = [(p.slug, p.title, p.summary) for p in db.scalars(select(WikiPageRecord).where(
            WikiPageRecord.kb_id == kb_id, WikiPageRecord.slug.in_(slugs), WikiPageRecord.folder_id.is_(None)))]
    if not rows:
        return
    items = '\n'.join(f'- slug: {s} | name: {t} | {d}' for s, t, d in rows)
    reply = await _ask(factory, ids, model, 'You organize a wiki directory. Reply with JSON only.', prompts.render(
        prompts.TAXONOMY_PLAN_PROMPT, ExistingTaxonomy='\n'.join(folders) or '(none yet)', Items=items, Language=language), 1500)
    assigned = rules.parse_taxonomy(reply, {s for s, _, _ in rows})
    with factory() as db, db.begin():
        kb = db.get(KnowledgeBaseRecord, kb_id)
        for slug, path in assigned.items():
            page = wiki.find(db, kb_id, slug)
            if page is None or page.folder_id is not None or not path:
                continue  # a user's choice or an earlier filing is never churned
            page.folder_id, page.category_path = wiki.ensure_folders(db, kb, path), path


async def _refresh_index_page(factory, ids, model, kb_id: UUID, language: str, change: str) -> None:
    with factory() as db:
        summaries = [f'- {p.title}: {p.summary}' for p in db.scalars(select(WikiPageRecord).where(
            WikiPageRecord.kb_id == kb_id, WikiPageRecord.page_type == 'summary', WikiPageRecord.status == 'published')
            .order_by(WikiPageRecord.updated_at.desc()).limit(40))]
        current = wiki.find(db, kb_id, 'index')
        existing = current.content if current else ''
    if not summaries:
        return
    template, values = (prompts.INDEX_INTRO_UPDATE_PROMPT, {'ExistingIntro': existing, 'ChangeDescription': change}) \
        if existing else (prompts.INDEX_INTRO_PROMPT, {})
    reply = await _ask(factory, ids, model, 'You are a wiki editor.', prompts.render(
        template, DocumentSummaries='\n'.join(summaries), Language=language, **values), 600)
    intro = reply.strip()
    if not intro:
        return
    with factory() as db, db.begin():
        kb = db.get(KnowledgeBaseRecord, kb_id)
        page = wiki.find(db, kb_id, 'index')
        wiki.write_page(db, kb, page, slug='index', source='pipeline', title='Index', page_type='index', content=intro,
                        summary='Wiki index')


# ---------------------------------------------------------------- retraction

async def retract(factory: sessionmaker[Session], kb_id: UUID, document_id: UUID) -> None:
    await retract_pages(factory, kb_id, str(document_id))
    with factory() as db:
        kb = db.get(KnowledgeBaseRecord, kb_id)
        if kb is None or kb.status != 'active':
            return
        ids, config = (kb.tenant_id, kb.created_by), config_of(kb)
    await _refresh_index_page(factory, ids, config['model_id'], kb_id, config['language'], 'A document was removed.')


async def retract_pages(factory, kb_id: UUID, doc_id: str, *, only_types: tuple[str, ...] | None = None,
                        only_slugs: set[str] | None = None) -> None:
    """Remove ``doc_id`` as a source: delete pages left without sources, rewrite the others without its facts."""
    with factory() as db:
        kb = db.get(KnowledgeBaseRecord, kb_id)
        if kb is None:
            return
        config, ids = config_of(kb), (kb.tenant_id, kb.created_by)
        pages = [p for p in db.scalars(select(WikiPageRecord).where(
            WikiPageRecord.kb_id == kb_id, WikiPageRecord.status != 'deleting')) if doc_id in (p.source_refs or [])]
        deleted_summary = next((p.content for p in pages if p.page_type == 'summary'), '')
        valid = {p for p in db.scalars(select(WikiPageRecord.slug).where(
            WikiPageRecord.kb_id == kb_id, WikiPageRecord.status != 'deleting'))}
        remaining = {p.slug: p.content for p in db.scalars(select(WikiPageRecord).where(
            WikiPageRecord.kb_id == kb_id, WikiPageRecord.page_type == 'summary', WikiPageRecord.status == 'published'))
            if doc_id not in (p.source_refs or [])}
        todo = [(p.slug, p.page_type, p.title, list(p.aliases or []), p.content, [s for s in p.source_refs if s != doc_id])
                for p in pages if (only_types is None or p.page_type in only_types) and (only_slugs is None or p.slug in only_slugs)]
    gone = [t for t in todo if not t[5] and t[1] in ('summary', 'entity', 'concept')]
    for slug, *_ in gone:  # pages left without sources go first, so rewritten pages no longer link to them
        with factory() as db, db.begin():
            page = wiki.find(db, kb_id, slug)
            if page is not None:
                wiki.mark_deleting(db, page)
                wiki.refresh_in_links(db, kb_id)
    with factory() as db:
        valid = set(db.scalars(select(WikiPageRecord.slug).where(
            WikiPageRecord.kb_id == kb_id, WikiPageRecord.status != 'deleting')))
    gone_slugs = {t[0] for t in gone}
    if gone_slugs:  # other pages must not keep links to the pages that just disappeared
        with factory() as db, db.begin():
            kb = db.get(KnowledgeBaseRecord, kb_id)
            for page in db.scalars(select(WikiPageRecord).where(WikiPageRecord.kb_id == kb_id, WikiPageRecord.status != 'deleting')):
                if gone_slugs & set(page.out_links or []):
                    wiki.write_page(db, kb, page, source='pipeline', content=rules.sanitize_links(page.content, valid, page.slug))
    for slug, page_type, title, aliases, content, sources in [t for t in todo if t not in gone]:
        new_body, new_summary = content, None
        if page_type in ('entity', 'concept') and config['model_id'] is not None:
            others = '\n\n'.join(c[:1500] for c in list(remaining.values())[:6])[:6000]
            reply = await _ask(factory, ids, config['model_id'], _system(config['content_instructions']), _page_user_prompt(
                slug=slug, title=title, page_type=page_type, aliases=aliases, existing=content, new_content='',
                deleted=deleted_summary[:6000], remaining=others, valid=_slug_lines([(s, s.split('/', 1)[-1], []) for s in sorted(valid - {slug})][:400]),
                language=config['language']), 4000)
            new_summary, rewritten = rules.split_summary(reply)
            if rewritten.strip():
                new_body = rewritten
        with factory() as db, db.begin():
            kb = db.get(KnowledgeBaseRecord, kb_id)
            page = wiki.find(db, kb_id, slug)
            if page is not None:
                wiki.write_page(db, kb, page, source='pipeline', content=rules.sanitize_links(new_body, valid, slug),
                                summary=new_summary or page.summary, source_refs=sources)
    with factory() as db, db.begin():
        wiki.refresh_in_links(db, kb_id)


# ---------------------------------------------------------------- page indexing

def index_texts(page: WikiPageRecord) -> list[str]:
    """Index passages of a page: the head (title, aliases, summary) and its content in ~700 character pieces."""
    head = ' '.join([page.title, *(page.aliases or []), page.summary]).strip()
    rows = [head] if head else []
    buffer = ''
    for block in re.split(r'\n\s*\n', page.content or ''):
        block = block.strip()
        if not block:
            continue
        if buffer and len(buffer) + len(block) > ROW_CHARS:
            rows.append(buffer)
            buffer = ''
        buffer = f'{buffer}\n\n{block}'.strip()
        while len(buffer) > ROW_CHARS * 2:  # one huge paragraph
            rows.append(buffer[:ROW_CHARS * 2])
            buffer = buffer[ROW_CHARS * 2:]
    if buffer:
        rows.append(buffer)
    return [f'{page.title}\n{r}' if i else r for i, r in enumerate(rows[:MAX_ROWS])]


async def index_tick(factory: sessionmaker[Session], limit: int = INDEX_BATCH) -> int:
    """Index pending pages and remove deleted ones; returns how many pages were handled."""
    with factory() as db:
        pending = db.execute(select(WikiPageRecord.id, WikiPageRecord.kb_id, WikiPageRecord.status).where(
            WikiPageRecord.index_state == 'pending').order_by(WikiPageRecord.kb_id, WikiPageRecord.updated_at).limit(limit)).all()
    by_kb: dict[UUID, list[tuple[UUID, str]]] = {}
    for page_id, kb_id, status in pending:
        by_kb.setdefault(kb_id, []).append((page_id, status))
    handled = 0
    for kb_id, rows in by_kb.items():
        handled += await _index_base(factory, kb_id, rows)
    return handled


async def _index_base(factory, kb_id: UUID, rows: list[tuple[UUID, str]]) -> int:
    with factory() as db:
        kb = db.get(KnowledgeBaseRecord, kb_id)
        if kb is None or kb.status != 'active':
            return 0
        pages = {p.id: p for p in db.scalars(select(WikiPageRecord).where(WikiPageRecord.id.in_([r[0] for r in rows])))}
        texts = {pid: index_texts(p) for pid, p in pages.items() if p.status != 'deleting' and p.page_type not in wiki.SYSTEM_TYPES}
        removed = [pid for pid, p in pages.items() if p.status == 'deleting']
        versions = {pid: p.version for pid, p in pages.items()}
        use_vectors = bool(kb.indexing.get('vector')) and kb.embedding_model_version_id is not None
        keyword = bool(kb.indexing.get('keyword'))
        ctx = (kb.tenant_id, kb.created_by, kb.embedding_model_version_id, kb.embedding_dimension)
        index = stores.vector_index_for(db, kb)
    tenant_id, owner_id, model_id, dimension = ctx
    collection = collection_name(str(kb_id))
    error: Exception | None = None
    try:
        flat = [t for ts in texts.values() for t in ts]
        vectors: list = []
        if use_vectors and flat:
            client = embedding.embedder(factory, tenant_id, owner_id, model_id, 'knowledge.embedding')
            try:
                vectors = await client.embed(flat)
            finally:
                await client.close()
            if vectors and dimension and len(vectors[0]) != dimension:
                raise ValueError('embedding size differs from the base; rebuild the base')
            dimension = len(vectors[0]) if vectors else dimension
        await index.delete_versions(collection, [str(p) for p in [*texts, *removed]])
        out, cursor = [], 0
        for pid, page_texts in texts.items():
            for n, text in enumerate(page_texts):
                out.append(IndexRow(f'w:{pid}:{n}', str(kb_id), str(pid), tokenize(text) if keyword else '',
                                    vectors[cursor] if use_vectors else None))
                cursor += 1
        if out:
            await index.upsert(collection, out, dimension=dimension if use_vectors else None)
    except Exception as exc:
        error = exc
        logger.warning('wiki indexing failed', extra={'kb_id': str(kb_id), 'error': type(exc).__name__})
    finally:
        await index.close()
    with factory() as db, db.begin():
        for pid, version in versions.items():
            page = db.get(WikiPageRecord, pid)
            if page is None:
                continue
            if error is None:
                if page.status == 'deleting':
                    db.delete(page)
                elif page.version == version:  # an edit during indexing keeps the page pending
                    page.index_state, page.index_error = 'ready', None
            else:
                page.index_attempts += 1
                page.index_error = str(error)[:500]
                if page.index_attempts >= MAX_INDEX_ATTEMPTS:
                    page.index_state = 'failed'
    return len(versions)


def scope_ids(db: Session, kb_id: UUID) -> tuple[str, ...]:
    """Searchable pages (published and indexed) of a wiki base; their ids act as index versions."""
    return tuple(sorted(str(i) for i in db.scalars(select(WikiPageRecord.id).where(
        WikiPageRecord.kb_id == kb_id, WikiPageRecord.status == 'published', WikiPageRecord.index_state == 'ready',
        WikiPageRecord.page_type.not_in(wiki.SYSTEM_TYPES)))))
