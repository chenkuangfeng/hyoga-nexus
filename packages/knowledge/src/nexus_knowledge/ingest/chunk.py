"""Chunking (decision 6, openspec 2026-11-06-knowledge-base K1/K4): strategies, separators, parent-child.

Sections come from :mod:`.parse` and carry a page or heading path; a chunk never spans two sections, except for
``legacy`` which cuts the joined text at fixed positions. Strategies (WeKnora ``chunking_config.strategy``):

- ``heading``: one chunk per section; a section longer than ``size`` is split further.
- ``heuristic``: adjacent *small* sections are merged up to ``size`` (slides, short sheets, many tiny headings), so
  chunks are not fragments.
- ``recursive``: sections are cut with the separator list (``separators`` or the defaults), preferring the earliest
  separator found in the last quarter of the window.
- ``legacy``: the joined text cut at fixed positions (Octop ``chunk_text``), no regard for boundaries.
- ``auto``: pick the first of heading → heuristic → recursive that fits the document (see :func:`plan`).

Parent-child (``parent_child``): parents of ``parent_size`` are produced with the chosen strategy and *not
indexed*; each parent is cut into children of ``child_size`` that are indexed. A search hit on a child returns its
parent's text (more context), with the child's position.

Offsets (`char_start`/`char_end`) are relative to the section text (the joined text for ``legacy``).
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field, replace

from .parse import Section

DEFAULT_SIZE = 800
DEFAULT_OVERLAP = 120
DEFAULT_PARENT = 4096
DEFAULT_CHILD = 384
MIN_SIZE, MAX_SIZE = 100, 10000
MAX_PARENT = 20000
STRATEGIES = ('auto', 'heading', 'heuristic', 'recursive', 'legacy')
DEFAULT_SEPARATORS = ('\n\n', '\n', '。', '！', '？', '. ', '! ', '? ', '；', '; ', '，', ', ', ' ')
MAX_SEPARATORS = 20


@dataclass(frozen=True)
class ChunkConfig:
    size: int = DEFAULT_SIZE
    overlap: int = DEFAULT_OVERLAP
    strategy: str = 'auto'
    separators: tuple[str, ...] = ()
    parent_child: bool = False
    parent_size: int = DEFAULT_PARENT
    child_size: int = DEFAULT_CHILD

    @classmethod
    def from_settings(cls, size: int, overlap: int, extra: dict | None) -> 'ChunkConfig':
        """Config of a knowledge base: size and overlap columns plus ``settings['chunking_config']``."""
        extra = extra or {}
        separators = tuple(str(s) for s in (extra.get('separators') or ()) if str(s))
        config = cls(size, overlap, str(extra.get('strategy') or 'auto'), separators,
                     bool(extra.get('enable_parent_child')),
                     int(extra.get('parent_chunk_size') or DEFAULT_PARENT), int(extra.get('child_chunk_size') or DEFAULT_CHILD))
        config.validate()
        return config

    def validate(self) -> None:
        if not MIN_SIZE <= self.size <= MAX_SIZE:
            raise ValueError(f'chunk size must be between {MIN_SIZE} and {MAX_SIZE}')
        if not 0 <= self.overlap < self.size // 2:
            raise ValueError('chunk overlap must be at least 0 and less than half the chunk size')
        if self.strategy not in STRATEGIES:
            raise ValueError(f'chunking strategy must be one of {", ".join(STRATEGIES)}')
        if len(self.separators) > MAX_SEPARATORS:
            raise ValueError(f'at most {MAX_SEPARATORS} separators')
        if self.parent_child:
            if not 1 <= self.child_size <= MAX_SIZE or not MIN_SIZE <= self.parent_size <= MAX_PARENT:
                raise ValueError('parent size must be 100-20000 and child size 1-10000')
            if self.child_size >= self.parent_size:
                raise ValueError('child size must be smaller than parent size')


@dataclass(frozen=True)
class Chunk:
    ordinal: int
    content: str
    page: int | None
    section: tuple[str, ...]
    char_start: int
    char_end: int
    #: Ordinal of the parent chunk (children only).
    parent: int | None = None
    #: False for parents of a parent-child split: stored and readable, but not searched.
    indexed: bool = True


def validate(size: int, overlap: int) -> None:
    ChunkConfig(size, overlap).validate()


def _cut(text: str, start: int, size: int, separators: tuple[str, ...]) -> int:
    end = min(len(text), start + size)
    if end >= len(text):
        return len(text)
    floor = start + (size * 3) // 4
    for mark in separators:
        position = text.rfind(mark, floor, end)
        if position != -1:
            return position + len(mark)
    return end


def _windows(text: str, size: int, overlap: int, separators: tuple[str, ...]) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    start = 0
    while start < len(text):
        end = _cut(text, start, size, separators)
        body = text[start:end]
        if body.strip():
            lead = len(body) - len(body.lstrip())
            spans.append((start + lead, start + len(body.rstrip())))
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return spans


@dataclass
class _Piece:
    text: str
    page: int | None
    section: tuple[str, ...]
    start: int


def _pieces(sections: list[Section], config: ChunkConfig, size: int, overlap: int, strategy: str) -> list[_Piece]:
    separators = config.separators or DEFAULT_SEPARATORS
    out: list[_Piece] = []
    if strategy == 'legacy':
        text = '\n\n'.join(s.text for s in sections)
        first = sections[0] if sections else Section('')
        for a, b in _windows(text, size, overlap, ()):
            out.append(_Piece(text[a:b], first.page, first.section, a))
        return out
    units = sections
    if strategy == 'heuristic':
        units = _merge_small(sections, size)
    for unit in units:
        for a, b in _windows(unit.text, size, overlap, separators):
            out.append(_Piece(unit.text[a:b], unit.page, unit.section, a))
    return out


def _merge_small(sections: list[Section], size: int) -> list[Section]:
    merged: list[Section] = []
    for section in sections:
        last = merged[-1] if merged else None
        if last is not None and len(last.text) + len(section.text) + 2 <= size and last.page == section.page:
            merged[-1] = Section(last.text + '\n\n' + section.text, last.page, last.section)
        else:
            merged.append(section)
    return merged


@dataclass
class Plan:
    selected: str
    chain: list[str]
    rejected: list[dict[str, str]] = field(default_factory=list)
    profile: dict[str, int] = field(default_factory=dict)


def plan(sections: list[Section], config: ChunkConfig) -> Plan:
    """The strategy used for these sections and why the earlier tiers of ``auto`` were rejected."""
    headed = sum(1 for s in sections if s.section)
    lengths = [len(s.text) for s in sections]
    profile = {'total_chars': sum(lengths), 'sections': len(sections), 'headed_sections': headed,
               'short_sections': sum(1 for n in lengths if n < config.size // 3)}
    if config.strategy != 'auto':
        return Plan(config.strategy, [config.strategy], [], profile)
    rejected: list[dict[str, str]] = []
    if headed >= 2:
        return Plan('heading', ['heading', 'heuristic', 'recursive', 'legacy'], rejected, profile)
    rejected.append({'tier': 'heading', 'reason': 'fewer than two headed sections'})
    if len(sections) >= 3 and profile['short_sections'] * 2 >= len(sections):
        return Plan('heuristic', ['heading', 'heuristic', 'recursive', 'legacy'], rejected, profile)
    rejected.append({'tier': 'heuristic', 'reason': 'sections are not mostly short'})
    return Plan('recursive', ['heading', 'heuristic', 'recursive', 'legacy'], rejected, profile)


def chunk_document(sections: list[Section], config: ChunkConfig) -> list[Chunk]:
    """Chunks of a document, numbered from 0 (parents first in a parent-child split)."""
    config.validate()
    strategy = plan(sections, config).selected
    if not config.parent_child:
        return [Chunk(i, p.text, p.page, p.section, p.start, p.start + len(p.text))
                for i, p in enumerate(_pieces(sections, config, config.size, config.overlap, strategy))]
    parents = _pieces(sections, config, config.parent_size, 0, strategy)
    chunks = [Chunk(i, p.text, p.page, p.section, p.start, p.start + len(p.text), None, False)
              for i, p in enumerate(parents)]
    overlap = min(config.overlap, config.child_size // 4)
    separators = config.separators or DEFAULT_SEPARATORS
    for index, parent in enumerate(parents):
        for a, b in _windows(parent.text, config.child_size, overlap, separators):
            chunks.append(Chunk(len(chunks), parent.text[a:b], parent.page, parent.section, parent.start + a,
                                parent.start + b, parent=index, indexed=True))
    return chunks


def chunk_sections(sections: list[Section], *, size: int = DEFAULT_SIZE, overlap: int = DEFAULT_OVERLAP) -> list[Chunk]:
    """Chunks with the default strategy (kept for callers that only know size and overlap)."""
    return chunk_document(sections, ChunkConfig(size, overlap))


def preview(sections: list[Section], config: ChunkConfig, limit: int = 200) -> dict:
    """Debug view of the chunking (WeKnora chunker preview): strategy, chunks and size statistics."""
    chosen = plan(sections, config)
    chunks = chunk_document(sections, config)
    shown = [c for c in chunks if c.parent is None or not config.parent_child or c.indexed][:limit]
    sizes = [len(c.content) for c in chunks if c.indexed] or [0]
    return {
        'selected_tier': chosen.selected, 'tier_chain': chosen.chain, 'rejected': chosen.rejected,
        'profile': chosen.profile,
        'chunks': [{'seq': c.ordinal, 'start': c.char_start, 'end': c.char_end, 'size_chars': len(c.content),
                    'size_tokens_approx': max(1, len(c.content) // 2), 'context_header': ' > '.join(c.section),
                    'content': c.content, 'parent': c.parent} for c in shown],
        'stats': {'count': len(sizes), 'avg_chars': round(statistics.fmean(sizes), 1), 'min_chars': min(sizes),
                  'max_chars': max(sizes), 'stddev_chars': round(statistics.pstdev(sizes), 1),
                  **({'truncated_to': limit} if len(chunks) > limit else {})},
    }
