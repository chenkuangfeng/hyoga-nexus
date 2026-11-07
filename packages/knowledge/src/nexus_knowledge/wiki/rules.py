"""Pure Wiki rules: slugs, ``[[link]]`` handling, category paths, model reply parsing, duplicate candidates.

Reference: WeKnora ``internal/application/service/wiki_page.go``, ``wiki_ingest*.go`` and ``wiki_linkify.go``.
Nothing here touches the database or a model.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

PAGE_TYPES = ('index', 'log', 'summary', 'entity', 'concept', 'synthesis', 'comparison')
#: Types produced by the ingest pipeline; the rest are written by people or agents.
GENERATED_TYPES = ('summary', 'entity', 'concept')
MAX_SLUG = 200
MAX_CATEGORY_DEPTH = 2
MAX_LABEL = 60

_SLUG_SEGMENT = re.compile(r'[^\w\-]+', re.UNICODE)
LINK = re.compile(r'\[\[([^\[\]|]+?)(?:\|([^\[\]]*?))?\]\]')
_SUMMARY = re.compile(r'^\s*SUMMARY:\s*(.+?)\s*$', re.I)
_FENCE = re.compile(r'^```[a-zA-Z]*\s*|\s*```$')


def normalize_slug(raw: str) -> str:
    """Lowercase ``a/b-c`` form: segments of letters, digits, ``_`` and ``-``; '' when nothing is left."""
    segments = []
    for part in str(raw or '').strip().strip('/').split('/'):
        part = _SLUG_SEGMENT.sub('-', part.strip().lower()).strip('-_')
        if part:
            segments.append(part)
    return '/'.join(segments)[:MAX_SLUG].strip('/')


def slug_for(kind: str, slug: str, name: str) -> str:
    """``entity/x`` or ``concept/x`` for an extracted item; the model's slug is kept when it already has the prefix."""
    cleaned = normalize_slug(slug)
    tail = cleaned.split('/', 1)[1] if '/' in cleaned and cleaned.split('/', 1)[0] in PAGE_TYPES else cleaned
    tail = normalize_slug(tail) or normalize_slug(name)
    return f'{kind}/{tail}' if tail else ''


def extract_links(content: str) -> list[str]:
    """Distinct slugs referenced by ``[[slug]]`` / ``[[slug|name]]``, in order of appearance."""
    out: list[str] = []
    for match in LINK.finditer(content or ''):
        slug = normalize_slug(match.group(1))
        if slug and slug not in out:
            out.append(slug)
    return out


def sanitize_links(content: str, valid: set[str], self_slug: str) -> str:
    """Replace a link to an unknown page (or to the page itself) by its display text, keep the others."""
    def swap(match: re.Match[str]) -> str:
        slug = normalize_slug(match.group(1))
        if slug in valid and slug != self_slug:
            return match.group(0)
        return (match.group(2) or match.group(1).split('/')[-1]).strip()
    return LINK.sub(swap, content or '')


def clean_category_path(path: object) -> list[str]:
    """At most two non-empty labels without slashes, duplicates of the parent removed."""
    if not isinstance(path, (list, tuple)):
        return []
    out: list[str] = []
    for label in path:
        text = re.sub(r'\s+', ' ', str(label or '').replace('/', ' ').replace('\\', ' ')).strip()[:MAX_LABEL]
        if text and (not out or out[-1].casefold() != text.casefold()):
            out.append(text)
    return out[:MAX_CATEGORY_DEPTH]


def split_summary(reply: str) -> tuple[str, str]:
    """(summary, body) of a ``SUMMARY: ...`` first line followed by Markdown; summary is '' when absent."""
    lines = (reply or '').strip().splitlines()
    while lines and not lines[0].strip():
        lines.pop(0)
    if lines:
        match = _SUMMARY.match(lines[0])
        if match:
            return match.group(1).strip()[:500], '\n'.join(lines[1:]).strip()
    return '', '\n'.join(lines).strip()


@dataclass
class Extracted:
    """One entity or concept proposed for a document."""

    kind: str
    name: str
    slug: str
    aliases: list[str] = field(default_factory=list)
    description: str = ''
    details: str = ''


def _json_object(text: str) -> dict:
    cleaned = _FENCE.sub('', (text or '').strip())
    start, end = cleaned.find('{'), cleaned.rfind('}')
    if start < 0 or end <= start:
        return {}
    try:
        value = json.loads(cleaned[start:end + 1])
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def parse_extraction(reply: str, limit: int = 40) -> list[Extracted]:
    """Entities and concepts of a reply; malformed items are skipped and slugs are forced to their kind's prefix."""
    data = _json_object(reply)
    out: list[Extracted] = []
    seen: set[str] = set()
    for key, kind in (('entities', 'entity'), ('concepts', 'concept')):
        for raw in data.get(key) or []:
            if not isinstance(raw, dict):
                continue
            name = str(raw.get('name') or '').strip()[:160]
            slug = slug_for(kind, str(raw.get('slug') or ''), name)
            if not name or not slug or slug in seen:
                continue
            seen.add(slug)
            aliases = [a for a in dict.fromkeys(str(x).strip()[:160] for x in raw.get('aliases') or [] if str(x).strip())
                       if a.casefold() != name.casefold()][:12]
            out.append(Extracted(kind, name, slug, aliases, str(raw.get('description') or '').strip()[:600],
                                 str(raw.get('details') or '').strip()[:4000]))
    return out[:limit]


def parse_merges(reply: str, new_slugs: set[str], allowed: dict[str, set[str]]) -> dict[str, str]:
    """``{new slug: existing slug}``; a target must be one of that item's own candidates and of the same type."""
    merges = _json_object(reply).get('merges')
    out: dict[str, str] = {}
    if not isinstance(merges, dict):
        return out
    for new, old in merges.items():
        new, old = normalize_slug(str(new)), normalize_slug(str(old))
        if new in new_slugs and old in allowed.get(new, set()) and new.split('/')[0] == old.split('/')[0]:
            out[new] = old
    return out


def parse_taxonomy(reply: str, slugs: set[str]) -> dict[str, list[str]]:
    """``{slug: category path}`` for the slugs that were asked about."""
    out: dict[str, list[str]] = {}
    for raw in _json_object(reply).get('assignments') or []:
        if isinstance(raw, dict):
            slug = normalize_slug(str(raw.get('slug') or ''))
            if slug in slugs:
                out[slug] = clean_category_path(raw.get('path'))
    return out


_WORD = re.compile(r'\w+', re.UNICODE)


def _name_keys(name: str, aliases: list[str]) -> set[str]:
    return {re.sub(r'\W+', '', n).casefold() for n in [name, *aliases] if n}


def similar_pages(item: Extracted, pages: list[tuple[str, str, list[str]]], limit: int = 5) -> list[str]:
    """Slugs of existing ``(slug, title, aliases)`` pages whose name or alias resembles the item (same type only).

    A cheap lexical pre-selection (equal, contained or sharing at least half of the words) that bounds what the
    model has to compare; the model decides the actual merge.
    """
    keys = _name_keys(item.name, item.aliases)
    words = {w.casefold() for n in [item.name, *item.aliases] for w in _WORD.findall(n)}
    scored: list[tuple[float, str]] = []
    for slug, title, aliases in pages:
        if slug.split('/')[0] != item.kind:
            continue
        other = _name_keys(title, aliases)
        score = 0.0
        if keys & other:
            score = 2.0
        elif any(a and b and (a in b or b in a) for a in keys for b in other):
            score = 1.0
        else:
            theirs = {w.casefold() for n in [title, *aliases] for w in _WORD.findall(n)}
            if words and theirs:
                score = len(words & theirs) / len(words | theirs)
                score = score if score >= 0.5 else 0.0
        if score:
            scored.append((score, slug))
    scored.sort(key=lambda p: (-p[0], p[1]))
    return [slug for _, slug in scored[:limit]]
