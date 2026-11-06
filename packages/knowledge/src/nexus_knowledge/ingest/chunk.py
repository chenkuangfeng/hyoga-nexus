"""Chunking: sections are split into overlapping windows that keep their page and heading path (decision 6).

Each section is chunked on its own, so a chunk never spans two PDF pages or two Markdown sections. Inside a
section the window is ``size`` characters with ``overlap`` characters shared with the previous window; the
cut prefers a paragraph break, then a sentence end, then whitespace in the last quarter of the window, so
chunks rarely end mid-sentence (Octop ``chunk_text`` plus the separator preference of WeKnora's
``recursive`` strategy). Character offsets are relative to the section text.
"""
from __future__ import annotations

from dataclasses import dataclass

from .parse import Section

DEFAULT_SIZE = 800
DEFAULT_OVERLAP = 120
MIN_SIZE, MAX_SIZE = 100, 10000

_BREAKS = ('\n\n', '\n', '。', '！', '？', '. ', '! ', '? ', '；', '; ', '，', ', ', ' ')


@dataclass(frozen=True, slots=True)
class Chunk:
    ordinal: int
    content: str
    page: int | None
    section: tuple[str, ...]
    char_start: int
    char_end: int


def validate(size: int, overlap: int) -> None:
    if not MIN_SIZE <= size <= MAX_SIZE:
        raise ValueError(f'chunk size must be between {MIN_SIZE} and {MAX_SIZE}')
    if not 0 <= overlap < size // 2:
        raise ValueError('chunk overlap must be at least 0 and less than half the chunk size')


def _cut(text: str, start: int, size: int) -> int:
    end = min(len(text), start + size)
    if end >= len(text):
        return len(text)
    floor = start + (size * 3) // 4
    for mark in _BREAKS:
        position = text.rfind(mark, floor, end)
        if position != -1:
            return position + len(mark)
    return end


def chunk_sections(sections: list[Section], *, size: int = DEFAULT_SIZE,
                   overlap: int = DEFAULT_OVERLAP) -> list[Chunk]:
    """Chunks of every section, numbered from 0 in document order. Whitespace-only windows are skipped."""
    validate(size, overlap)
    chunks: list[Chunk] = []
    for section in sections:
        text = section.text
        start = 0
        while start < len(text):
            end = _cut(text, start, size)
            body = text[start:end]
            if body.strip():
                lead = len(body) - len(body.lstrip())
                trail = len(body.rstrip())
                chunks.append(Chunk(len(chunks), body.strip(), section.page, section.section,
                                    start + lead, start + trail))
            if end >= len(text):
                break
            start = max(end - overlap, start + 1)
    return chunks
