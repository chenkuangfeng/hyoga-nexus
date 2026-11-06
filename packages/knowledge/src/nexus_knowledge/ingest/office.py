"""Office document text extraction with the standard library (OOXML = zip + XML; no new dependencies).

- ``.docx``: paragraphs of ``word/document.xml`` in order; ``Heading N`` styles become Markdown-style headings so
  the chunker can use them as section titles; table cells are joined with `` | `` per row.
- ``.pptx``: one section per slide (``page`` = slide number), text of every shape and table cell.
- ``.xlsx``: one section per sheet, rows as ``header: value`` pairs like CSV (``section`` = sheet name).

Safety: the archive is read through a size budget (:data:`MAX_UNCOMPRESSED`) so a zip bomb cannot exhaust memory,
XML is parsed with ``defusedxml``-style restrictions (DTDs and entities are rejected by ``xml.etree`` in recent
Pythons only partially, so the parser here refuses any document that declares a DOCTYPE).
"""
from __future__ import annotations

import io
import re
import xml.etree.ElementTree as ET
import zipfile
from typing import Iterator

from .parse import ParseError, Section

MAX_UNCOMPRESSED = 64 * 1024 * 1024
MAX_ROWS_PER_SHEET = 20000
_W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
_A = '{http://schemas.openxmlformats.org/drawingml/2006/main}'
_S = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
_HEADING = re.compile(r'^(?:heading|标题)\s*(\d)$', re.I)


def _open(data: bytes) -> zipfile.ZipFile:
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ParseError(f'invalid Office file: {exc}') from exc
    if sum(info.file_size for info in archive.infolist()) > MAX_UNCOMPRESSED:
        raise ParseError('Office file is too large when unpacked')
    return archive


def _xml(archive: zipfile.ZipFile, name: str) -> ET.Element | None:
    try:
        raw = archive.read(name)
    except KeyError:
        return None
    if b'<!DOCTYPE' in raw[:2048] or b'<!ENTITY' in raw[:2048]:
        raise ParseError('Office file contains a DTD, which is not accepted')
    try:
        return ET.fromstring(raw)
    except ET.ParseError as exc:
        raise ParseError(f'invalid XML in {name}: {exc}') from exc


def _text(node: ET.Element, tag: str) -> str:
    return ''.join(t.text or '' for t in node.iter(tag))


def parse_docx(data: bytes) -> list[Section]:
    archive = _open(data)
    root = _xml(archive, 'word/document.xml')
    if root is None:
        raise ParseError('not a Word document (word/document.xml missing)')
    styles = _heading_styles(archive)
    lines: list[str] = []
    body = root.find(f'{_W}body')
    for child in (body if body is not None else []):
        if child.tag == f'{_W}p':
            text = _text(child, f'{_W}t').strip()
            if not text:
                continue
            style = child.find(f'{_W}pPr/{_W}pStyle')
            level = styles.get(style.get(f'{_W}val', '') if style is not None else '')
            lines.append(f'{"#" * level} {text}' if level else text)
        elif child.tag == f'{_W}tbl':
            for row in child.iter(f'{_W}tr'):
                cells = [' '.join(_text(cell, f'{_W}t').split()) for cell in row.findall(f'{_W}tc')]
                if any(cells):
                    lines.append(' | '.join(cells))
    from .parse import parse_markdown
    return parse_markdown('\n'.join(lines))


def _heading_styles(archive: zipfile.ZipFile) -> dict[str, int]:
    root = _xml(archive, 'word/styles.xml')
    out: dict[str, int] = {}
    if root is None:
        return out
    for style in root.iter(f'{_W}style'):
        name = style.find(f'{_W}name')
        match = _HEADING.match(name.get(f'{_W}val', '') if name is not None else '')
        if match:
            out[style.get(f'{_W}styleId', '')] = max(1, min(int(match.group(1)), 6))
    return out


def _slide_number(name: str) -> int:
    match = re.search(r'slide(\d+)\.xml$', name)
    return int(match.group(1)) if match else 0


def parse_pptx(data: bytes) -> list[Section]:
    archive = _open(data)
    names = sorted((n for n in archive.namelist() if re.fullmatch(r'ppt/slides/slide\d+\.xml', n)), key=_slide_number)
    if not names:
        raise ParseError('not a PowerPoint file (no slides)')
    sections = []
    for name in names:
        root = _xml(archive, name)
        paragraphs = [''.join(t.text or '' for t in p.iter(f'{_A}t')).strip() for p in root.iter(f'{_A}p')]
        text = '\n'.join(p for p in paragraphs if p)
        if text:
            sections.append(Section(text, page=_slide_number(name)))
    return sections


def _shared_strings(archive: zipfile.ZipFile) -> list[str]:
    root = _xml(archive, 'xl/sharedStrings.xml')
    if root is None:
        return []
    return [_text(item, f'{_S}t') for item in root.findall(f'{_S}si')]


def _sheets(archive: zipfile.ZipFile) -> Iterator[tuple[str, str]]:
    """``(sheet name, part name)`` in workbook order."""
    workbook = _xml(archive, 'xl/workbook.xml')
    rels = _xml(archive, 'xl/_rels/workbook.xml.rels')
    if workbook is None:
        raise ParseError('not an Excel workbook (xl/workbook.xml missing)')
    targets = {r.get('Id'): r.get('Target', '') for r in (rels if rels is not None else [])}
    rid = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id'
    for sheet in workbook.iter(f'{_S}sheet'):
        target = targets.get(sheet.get(rid), '')
        if target:
            yield sheet.get('name', ''), ('xl/' + target.lstrip('/')) if not target.startswith('/xl/') else target[1:]


def _column(ref: str) -> int:
    letters = re.match(r'[A-Z]+', ref or '')
    index = 0
    for ch in letters.group(0) if letters else '':
        index = index * 26 + ord(ch) - 64
    return max(index - 1, 0)


def parse_xlsx(data: bytes) -> list[Section]:
    archive = _open(data)
    strings = _shared_strings(archive)
    sections = []
    for name, part in _sheets(archive):
        root = _xml(archive, part)
        if root is None:
            continue
        rows: list[list[str]] = []
        for row in root.iter(f'{_S}row'):
            cells: dict[int, str] = {}
            for cell in row.findall(f'{_S}c'):
                value = cell.find(f'{_S}v')
                kind = cell.get('t')
                if kind == 's' and value is not None and value.text and value.text.isdigit():
                    text = strings[int(value.text)] if int(value.text) < len(strings) else ''
                elif kind == 'inlineStr':
                    text = _text(cell, f'{_S}t')
                else:
                    text = (value.text or '') if value is not None else ''
                if text.strip():
                    cells[_column(cell.get('r', ''))] = text.strip()
            if cells:
                width = max(cells) + 1
                rows.append([cells.get(i, '') for i in range(width)])
            if len(rows) > MAX_ROWS_PER_SHEET:
                break
        if not rows:
            continue
        header, body = rows[0], rows[1:]
        if not body:
            text = ' | '.join(header)
        else:
            lines = []
            for values in body:
                pairs = [f'{(header[i] if i < len(header) and header[i] else i + 1)}: {v}'
                         for i, v in enumerate(values) if v]
                if pairs:
                    lines.append('; '.join(pairs))
            text = '\n\n'.join(lines)
        sections.append(Section(text, section=(name,)))
    return sections
