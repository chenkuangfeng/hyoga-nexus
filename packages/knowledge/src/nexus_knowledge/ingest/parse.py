"""Extract positioned text from the document types of the builtin parser (K1).

The result is a list of :class:`Section`: text plus where it came from (PDF page, Markdown heading path).
Chunking keeps these positions so a citation can point at a page or a section.

Supported in K1: plain text (``.txt``, ``.text``, ``.log``), Markdown (``.md``, ``.markdown``), ``.csv``,
``.tsv``, ``.json``, ``.jsonl`` and text PDFs (pypdf). Other types raise :class:`UnsupportedDocument`;
their parser engines are planned for K4. A scanned PDF yields no text and raises :class:`EmptyDocument`
(no OCR in K1).

Text decoding tries UTF-8 then GB18030, so Chinese files saved by Windows tools are not read as mojibake
(Octop ``infra/knowledge/parse.py`` ``_read_text``).
"""
from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import dataclass, field

PLAIN_SUFFIXES = frozenset({'.txt', '.text', '.log'})
MARKDOWN_SUFFIXES = frozenset({'.md', '.markdown'})
TABLE_SUFFIXES = frozenset({'.csv', '.tsv'})
JSON_SUFFIXES = frozenset({'.json', '.jsonl'})
PDF_SUFFIXES = frozenset({'.pdf'})
SUPPORTED_SUFFIXES = PLAIN_SUFFIXES | MARKDOWN_SUFFIXES | TABLE_SUFFIXES | JSON_SUFFIXES | PDF_SUFFIXES

_ENCODINGS = ('utf-8-sig', 'gb18030')
_HEADING = re.compile(r'^(#{1,6})\s+(.+?)\s*#*\s*$')
_FENCE = re.compile(r'^\s*(```|~~~)')


class ParseError(ValueError):
    """Base class; ``code`` is stored as the version's failure reason."""

    code = 'parse_failed'


class UnsupportedDocument(ParseError):
    code = 'unsupported_type'


class EmptyDocument(ParseError):
    code = 'empty_text'


@dataclass(frozen=True, slots=True)
class Section:
    """A run of text with its source position. ``page`` is 1-based for PDFs; ``section`` is the heading path."""

    text: str
    page: int | None = None
    section: tuple[str, ...] = field(default_factory=tuple)


def suffix_of(filename: str) -> str:
    dot = filename.rfind('.')
    return filename[dot:].lower() if dot > 0 else ''


def decode_text(data: bytes) -> str:
    """UTF-8 (with or without BOM), then GB18030; newlines normalized to ``\\n``."""
    for encoding in _ENCODINGS:
        try:
            text = data.decode(encoding)
        except UnicodeDecodeError:
            continue
        return text.replace('\r\n', '\n').replace('\r', '\n')
    return data.decode('utf-8', errors='replace').replace('\r\n', '\n').replace('\r', '\n')


def parse_document(filename: str, data: bytes) -> list[Section]:
    """Parse one file. Raises :class:`UnsupportedDocument` or :class:`EmptyDocument`."""
    suffix = suffix_of(filename)
    if suffix in PDF_SUFFIXES:
        sections = _parse_pdf(data)
    elif suffix in MARKDOWN_SUFFIXES:
        sections = parse_markdown(decode_text(data))
    elif suffix in PLAIN_SUFFIXES:
        sections = [Section(decode_text(data))]
    elif suffix in TABLE_SUFFIXES:
        sections = [Section(_parse_table(decode_text(data), '\t' if suffix == '.tsv' else ','))]
    elif suffix in JSON_SUFFIXES:
        sections = [Section(_parse_json(decode_text(data), suffix == '.jsonl'))]
    else:
        raise UnsupportedDocument(f'unsupported document type: {suffix or "(none)"}')
    sections = [s for s in sections if s.text.strip()]
    if not sections:
        raise EmptyDocument('document has no extractable text')
    return sections


def parse_markdown(text: str) -> list[Section]:
    """Split Markdown at ATX headings; each section carries the heading path. Headings in code fences are text."""
    sections: list[Section] = []
    path: list[str] = []
    levels: list[int] = []
    buffer: list[str] = []
    in_fence = False

    def flush() -> None:
        body = '\n'.join(buffer).strip()
        if body:
            sections.append(Section(body, section=tuple(path)))
        buffer.clear()

    for line in text.split('\n'):
        if _FENCE.match(line):
            in_fence = not in_fence
            buffer.append(line)
            continue
        match = None if in_fence else _HEADING.match(line)
        if match is None:
            buffer.append(line)
            continue
        flush()
        level, title = len(match.group(1)), match.group(2).strip()
        while levels and levels[-1] >= level:
            levels.pop()
            path.pop()
        levels.append(level)
        path.append(title)
        buffer.append(line)  # the heading stays in the text so the chunk reads naturally
    flush()
    return sections


def _parse_pdf(data: bytes) -> list[Section]:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(io.BytesIO(data))
        pages = [(index + 1, page.extract_text() or '') for index, page in enumerate(reader.pages)]
    except (PdfReadError, ValueError, KeyError, TypeError) as exc:
        raise ParseError(f'invalid PDF: {exc}') from exc
    return [Section(text.strip(), page=number) for number, text in pages if text.strip()]


def _parse_table(text: str, delimiter: str) -> str:
    """Rows as ``header: value`` lines so each chunk keeps column names (one blank line between rows)."""
    rows = list(csv.reader(io.StringIO(text), delimiter=delimiter))
    if not rows:
        return ''
    header, body = rows[0], rows[1:]
    if not body:
        return delimiter.join(header)
    lines = []
    for row in body:
        pairs = [f'{name.strip() or index + 1}: {value.strip()}'
                 for index, (name, value) in enumerate(zip(header, row)) if value.strip()]
        if pairs:
            lines.append('; '.join(pairs))
    return '\n\n'.join(lines)


def _parse_json(text: str, lines: bool) -> str:
    if lines:
        out = []
        for line in text.split('\n'):
            if not line.strip():
                continue
            try:
                out.append(json.dumps(json.loads(line), ensure_ascii=False))
            except json.JSONDecodeError:
                out.append(line)
        return '\n\n'.join(out)
    try:
        return json.dumps(json.loads(text), ensure_ascii=False, indent=2)
    except json.JSONDecodeError:
        return text
