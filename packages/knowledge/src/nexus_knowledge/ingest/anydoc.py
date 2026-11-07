"""``anydoc`` parser engine: in-process conversion of office and ebook formats (no external service).

WeKnora's ``anydoc`` engine wraps a native converter library and converts ``doc docx docm odt rtf ppt pptx pptm odp
xls xlsx xlsm ods epub csv pdf``. That library is not available to Python, so this module implements the same
file-type set natively (openspec 2026-11-06-knowledge-base K4):

- OOXML (`docx/docm`, `pptx/pptm`, `xlsx/xlsm`) reuse :mod:`.office`;
- OpenDocument (`odt`, `odp`, `ods`): ``content.xml`` of the zip (headings, paragraphs, tables, slides, sheets);
- ``rtf``: control-word tokenizer (groups of fonts, styles and pictures skipped, ``\\'hh`` and ``\\uN`` decoded);
- ``epub``: spine order from the OPF, each XHTML chapter becomes a section;
- ``html``/``htm``: headings, paragraphs, lists and tables to Markdown-like text;
- legacy binary ``doc`` (piece table of the Word FIB), ``ppt`` (text atoms of the PowerPoint stream) with
  ``olefile``, and ``xls`` with ``xlrd``.

Every parser caps the unpacked size and refuses DTDs, like :mod:`.office`. Scanned PDF and CSV are handled by the
builtin parser. Verified against the same fixture files WeKnora uses for its conversion tests.
"""
from __future__ import annotations

import io
import posixpath
import re
import struct
import xml.etree.ElementTree as ET
import zipfile
from html.parser import HTMLParser

from .office import MAX_ROWS_PER_SHEET, _open, _xml, parse_docx, parse_pptx, parse_xlsx
from .parse import ParseError, Section, parse_markdown

#: Extensions this engine converts, mapped to the parser that handles them.
SUPPORTED = ('csv', 'doc', 'docm', 'docx', 'epub', 'htm', 'html', 'odp', 'ods', 'odt', 'pdf', 'ppt', 'pptm', 'pptx',
             'rtf', 'xls', 'xlsm', 'xlsx')
#: Types the engine adds over the builtin parser (the builtin already reads docx/pptx/xlsx/csv/pdf).
EXTRA = ('doc', 'docm', 'epub', 'htm', 'html', 'odp', 'ods', 'odt', 'ppt', 'pptm', 'rtf', 'xls', 'xlsm')

MAX_TEXT = 8 * 1024 * 1024
_OFFICE_NS = {
    'text': 'urn:oasis:names:tc:opendocument:xmlns:text:1.0',
    'table': 'urn:oasis:names:tc:opendocument:xmlns:table:1.0',
    'draw': 'urn:oasis:names:tc:opendocument:xmlns:drawing:1.0',
}
_T = '{%s}' % _OFFICE_NS['text']
_TB = '{%s}' % _OFFICE_NS['table']
_DR = '{%s}' % _OFFICE_NS['draw']


# ---------------------------------------------------------------- OpenDocument

def _odf_text(node: ET.Element) -> str:
    """Text of an ODF node: `text:s` spaces, `text:tab`, `text:line-break` and nested spans."""
    out = [node.text or '']
    for child in node:
        if child.tag == _T + 's':
            out.append(' ' * int(child.get(_T + 'c', '1')))
        elif child.tag == _T + 'tab':
            out.append('\t')
        elif child.tag == _T + 'line-break':
            out.append('\n')
        else:
            out.append(_odf_text(child))
        out.append(child.tail or '')
    return ''.join(out)


def _odf_lines(node: ET.Element) -> list[str]:
    lines: list[str] = []
    for child in node:
        if child.tag == _T + 'h':
            level = max(1, min(int(child.get(_T + 'outline-level', '1') or 1), 6))
            text = ' '.join(_odf_text(child).split())
            if text:
                lines.append(f'{"#" * level} {text}')
        elif child.tag == _T + 'p':
            text = _odf_text(child).strip()
            if text:
                lines.append(text)
        elif child.tag in (_T + 'list', _T + 'list-item', _T + 'section', _DR + 'frame', _DR + 'text-box'):
            lines.extend(_odf_lines(child))
        elif child.tag == _TB + 'table':
            for row in child.iter(_TB + 'table-row'):
                cells = [' '.join(_odf_text(cell).split()) for cell in row.findall(_TB + 'table-cell')]
                if any(cells):
                    lines.append(' | '.join(cells))
        else:
            lines.extend(_odf_lines(child))
    return lines


def parse_odf(data: bytes, kind: str) -> list[Section]:
    archive = _open(data)
    root = _xml(archive, 'content.xml')
    if root is None:
        raise ParseError('not an OpenDocument file (content.xml missing)')
    body = root.find('{urn:oasis:names:tc:opendocument:xmlns:office:1.0}body')
    if body is None:
        raise ParseError('OpenDocument file has no body')
    if kind == 'odp':
        sections = []
        for number, page in enumerate(body.iter(_DR + 'page'), start=1):
            text = '\n'.join(_odf_lines(page))
            if text:
                sections.append(Section(text, page=number))
        return sections
    if kind == 'ods':
        sections = []
        for table in body.iter(_TB + 'table'):
            rows = []
            for row in table.findall(_TB + 'table-row'):
                cells = [' '.join(_odf_text(cell).split()) for cell in row.findall(_TB + 'table-cell')]
                if any(cells):
                    rows.append(cells)
                if len(rows) > MAX_ROWS_PER_SHEET:
                    break
            if rows:
                sections.append(Section(_rows_to_text(rows), section=(table.get(_TB + 'name', ''),)))
        return sections
    return parse_markdown('\n'.join(_odf_lines(body)))


def _rows_to_text(rows: list[list[str]]) -> str:
    """First row = header; later rows as ``header: value`` pairs (same shape as the xlsx parser)."""
    header, body = rows[0], rows[1:]
    if not body:
        return ' | '.join(header)
    lines = []
    for values in body:
        pairs = [f'{(header[i] if i < len(header) and header[i] else i + 1)}: {v}' for i, v in enumerate(values) if v]
        if pairs:
            lines.append('; '.join(pairs))
    return '\n\n'.join(lines)


# ---------------------------------------------------------------- RTF

_SKIP_DESTINATIONS = {'fonttbl', 'colortbl', 'stylesheet', 'info', 'pict', 'object', 'header', 'footer', 'headerl',
                      'headerr', 'footerl', 'footerr', 'themedata', 'colorschememapping', 'latentstyles',
                      'datastore', 'fldinst', 'xmlnstbl', 'listtable', 'listoverridetable', 'rsidtbl', 'generator',
                      'private', 'nonshppict', 'shpinst', 'bkmkstart', 'bkmkend', 'fcharset', 'panose', 'falt',
                      'private1'}
_RTF_TOKEN = re.compile(r"\\([a-zA-Z]+)(-?\d+)? ?|\\'([0-9a-fA-F]{2})|\\([^a-zA-Z])|([{}])|([^\\{}]+)", re.S)


def parse_rtf(data: bytes) -> list[Section]:
    text = data.decode('latin-1')
    if not text.lstrip().startswith('{\\rtf'):
        raise ParseError('not an RTF file')
    codepage = 'cp1252'
    match = re.search(r'\\ansicpg(\d+)', text)
    if match:
        codepage = f'cp{match.group(1)}'
    out: list[str] = []
    stack: list[tuple[bool, int]] = []  # (skipping, unicode skip count)
    skipping, uc_skip = False, 1
    pending_skip = 0
    pending_bytes = bytearray()

    def flush_bytes() -> None:
        if pending_bytes:
            try:
                out.append(bytes(pending_bytes).decode(codepage))
            except (UnicodeDecodeError, LookupError):
                out.append(bytes(pending_bytes).decode('cp1252', errors='replace'))
            pending_bytes.clear()

    last_group_start = False
    for match in _RTF_TOKEN.finditer(text):
        word, number, hexbyte, symbol, brace, plain = match.groups()
        if hexbyte is not None:
            if not skipping:
                pending_bytes.append(int(hexbyte, 16))
            continue
        flush_bytes()
        if brace == '{':
            stack.append((skipping, uc_skip))
            last_group_start = True
            continue
        if brace == '}':
            skipping, uc_skip = stack.pop() if stack else (False, 1)
            last_group_start = False
            continue
        if symbol is not None:
            if symbol == '*' and last_group_start:
                skipping = True  # \*\destination: ignorable
            elif symbol in '\\{}' and not skipping:
                out.append(symbol)
            elif symbol == '~' and not skipping:
                out.append(' ')
            last_group_start = False
            continue
        if word is not None:
            if last_group_start and word in _SKIP_DESTINATIONS:
                skipping = True
            last_group_start = False
            if skipping:
                continue
            if word in ('par', 'sect', 'page'):
                out.append('\n\n')
            elif word == 'line':
                out.append('\n')
            elif word == 'tab':
                out.append('\t')
            elif word in ('cell',):
                out.append(' | ')
            elif word == 'row':
                out.append('\n')
            elif word == 'uc' and number:
                uc_skip = int(number)
            elif word == 'u' and number:
                code = int(number)
                out.append(chr(code + 65536 if code < 0 else code))
                pending_skip = uc_skip
            continue
        if plain is not None:
            last_group_start = False
            if skipping:
                continue
            chunk = plain.replace('\r', '').replace('\n', '')
            if pending_skip and chunk:
                drop = min(pending_skip, len(chunk))
                chunk, pending_skip = chunk[drop:], pending_skip - drop
            out.append(chunk)
    flush_bytes()
    body = re.sub(r'[ \t]+\n', '\n', ''.join(out))
    body = re.sub(r'\n{3,}', '\n\n', body).strip()
    return parse_markdown(body[:MAX_TEXT])


# ---------------------------------------------------------------- HTML and EPUB

class _HtmlText(HTMLParser):
    BLOCK = {'p', 'div', 'section', 'article', 'li', 'tr', 'br', 'blockquote', 'pre', 'ul', 'ol', 'table'}
    SKIP = {'script', 'style', 'noscript', 'head', 'svg'}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip = 0
        self.heading = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
        elif tag in ('h1', 'h2', 'h3', 'h4', 'h5', 'h6'):
            self.parts.append('\n\n' + '#' * int(tag[1]) + ' ')
            self.heading += 1
        elif tag in ('td', 'th'):
            self.parts.append(' | ')
        elif tag in self.BLOCK:
            self.parts.append('\n')

    def handle_endtag(self, tag):
        if tag in self.SKIP:
            self.skip = max(0, self.skip - 1)
        elif tag in ('h1', 'h2', 'h3', 'h4', 'h5', 'h6'):
            self.parts.append('\n\n')
            self.heading = max(0, self.heading - 1)
        elif tag in self.BLOCK:
            self.parts.append('\n')

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(' '.join(data.split()) + (' ' if data[-1:].isspace() else '') if self.heading else
                              re.sub(r'[ \t\r\n]+', ' ', data))


def html_to_text(raw: str) -> str:
    parser = _HtmlText()
    parser.feed(raw)
    text = ''.join(parser.parts)
    text = re.sub(r'[ \t]*\n[ \t]*', '\n', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return re.sub(r'^\s*\|\s*', '', text, flags=re.M).strip()


def _decode_html(data: bytes) -> str:
    head = data[:2048].decode('ascii', errors='ignore').lower()
    match = re.search(r'charset=["\']?([a-z0-9_-]+)', head)
    for encoding in ([match.group(1)] if match else []) + ['utf-8-sig', 'gb18030']:
        try:
            return data.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode('utf-8', errors='replace')


def parse_html(data: bytes) -> list[Section]:
    return parse_markdown(html_to_text(_decode_html(data))[:MAX_TEXT])


def parse_epub(data: bytes) -> list[Section]:
    archive = _open(data)
    container = _xml(archive, 'META-INF/container.xml')
    if container is None:
        raise ParseError('not an EPUB (META-INF/container.xml missing)')
    rootfile = next((e.get('full-path') for e in container.iter() if e.tag.endswith('rootfile')), None)
    opf = _xml(archive, rootfile) if rootfile else None
    if opf is None:
        raise ParseError('EPUB package file is missing')
    base = posixpath.dirname(rootfile)
    manifest = {e.get('id'): e.get('href') for e in opf.iter() if e.tag.endswith('}item')}
    order = [manifest.get(e.get('idref')) for e in opf.iter() if e.tag.endswith('}itemref')]
    sections: list[Section] = []
    for href in order:
        if not href:
            continue
        name = posixpath.normpath(posixpath.join(base, href.split('#')[0]))
        if name.startswith('..'):
            continue
        try:
            raw = archive.read(name)
        except KeyError:
            continue
        sections.extend(s for s in parse_html(raw) if s.text.strip())
    return sections


# ---------------------------------------------------------------- legacy binary formats

def _ole(data: bytes):
    import olefile
    if data[:8] != b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1':  # olefile would treat short bytes as a file name
        raise ParseError('not an OLE2 (legacy Office) file')
    try:
        return olefile.OleFileIO(io.BytesIO(data))
    except Exception as exc:  # olefile raises plain OSError for corrupt files
        raise ParseError(f'invalid legacy Office file: {exc}') from exc


def _clean_word_text(text: str) -> str:
    """Remove Word field codes and control characters from raw document text."""
    text = re.sub(r'\x13[^\x14\x15]*\x14?', '', text)  # field begin ... separator: drop the instruction
    text = text.replace('\x15', '')
    text = text.replace('\r', '\n').replace('\x07', ' | ').replace('\x0b', '\n').replace('\x0c', '\n\n')
    text = re.sub(r'[\x00-\x08\x0e-\x1f]', '', text)
    text = re.sub(r'( \| )+\n', '\n', text)
    return re.sub(r'\n{3,}', '\n\n', text).strip()


def parse_doc(data: bytes) -> list[Section]:
    ole = _ole(data)
    try:
        if not ole.exists('WordDocument'):
            raise ParseError('not a Word document (no WordDocument stream)')
        word = ole.openstream('WordDocument').read()
        if len(word) < 0x01AA:
            raise ParseError('Word document header is truncated')
        flags = struct.unpack_from('<H', word, 0x0A)[0]
        table_name = '1Table' if flags & 0x0200 else '0Table'
        if not ole.exists(table_name):
            raise ParseError('Word table stream is missing')
        table = ole.openstream(table_name).read()
        ccp_text = struct.unpack_from('<i', word, 0x4C)[0]
        fc_clx, lcb_clx = struct.unpack_from('<II', word, 0x1A2)
    finally:
        ole.close()
    clx = table[fc_clx:fc_clx + lcb_clx]
    position = 0
    while position < len(clx) and clx[position] == 0x01:  # skip Prc blocks
        position += 3 + struct.unpack_from('<H', clx, position + 1)[0]
    if position >= len(clx) or clx[position] != 0x02:
        raise ParseError('Word piece table not found')
    size = struct.unpack_from('<I', clx, position + 1)[0]
    plc = clx[position + 5:position + 5 + size]
    count = (size - 4) // 12
    cps = struct.unpack_from(f'<{count + 1}I', plc, 0)
    chunks: list[str] = []
    for index in range(count):
        start, end = cps[index], min(cps[index + 1], ccp_text)
        if start >= ccp_text or end <= start:
            continue
        _, fc, _ = struct.unpack_from('<HIH', plc, (count + 1) * 4 + index * 8)
        length = end - start
        if fc & 0x40000000:
            offset = (fc & 0x3FFFFFFF) // 2
            chunks.append(word[offset:offset + length].decode('cp1252', errors='replace'))
        else:
            chunks.append(word[fc:fc + length * 2].decode('utf-16-le', errors='replace'))
    return parse_markdown(_clean_word_text(''.join(chunks))[:MAX_TEXT])


def parse_ppt(data: bytes) -> list[Section]:
    ole = _ole(data)
    try:
        if not ole.exists('PowerPoint Document'):
            raise ParseError('not a PowerPoint file (no PowerPoint Document stream)')
        stream = ole.openstream('PowerPoint Document').read()
    finally:
        ole.close()
    slides: list[list[str]] = []

    def walk(start: int, end: int, in_slide: bool) -> None:
        position = start
        while position + 8 <= end:
            ver_instance, rec_type, length = struct.unpack_from('<HHI', stream, position)
            body = position + 8
            if length > end - body:
                break
            if ver_instance & 0x0F == 0x0F:  # container
                is_slide = rec_type == 0x03EE
                if is_slide:
                    slides.append([])
                walk(body, body + length, in_slide or is_slide)
            elif in_slide and rec_type == 0x0FA0:  # TextCharsAtom (UTF-16LE)
                slides[-1].append(stream[body:body + length].decode('utf-16-le', errors='replace'))
            elif in_slide and rec_type == 0x0FA8:  # TextBytesAtom (cp1252)
                slides[-1].append(stream[body:body + length].decode('cp1252', errors='replace'))
            position = body + length

    walk(0, len(stream), False)
    sections = []
    for number, parts in enumerate(slides, start=1):
        text = '\n'.join(p.replace('\r', '\n').replace('\x0b', '\n').strip() for p in parts if p.strip())
        if text:
            sections.append(Section(text, page=number))
    return sections


def parse_xls(data: bytes) -> list[Section]:
    import xlrd
    try:
        book = xlrd.open_workbook(file_contents=data, on_demand=True)
    except Exception as exc:  # xlrd raises XLRDError and plain errors for corrupt input
        raise ParseError(f'invalid Excel file: {exc}') from exc
    sections = []
    try:
        for sheet in book.sheets():
            rows = []
            for r in range(min(sheet.nrows, MAX_ROWS_PER_SHEET)):
                cells = []
                for value in sheet.row_values(r):
                    if isinstance(value, float) and value.is_integer():
                        value = int(value)
                    cells.append(str(value).strip() if value not in ('', None) else '')
                if any(cells):
                    rows.append(cells)
            if rows:
                sections.append(Section(_rows_to_text(rows), section=(sheet.name,)))
    finally:
        book.release_resources()
    return sections


def parse(filename_suffix: str, data: bytes) -> list[Section]:
    """Sections of a file by extension (with the dot, lowercase)."""
    ext = filename_suffix.lstrip('.')
    if ext in ('docx', 'docm'):
        return parse_docx(data)
    if ext in ('pptx', 'pptm'):
        return parse_pptx(data)
    if ext in ('xlsx', 'xlsm'):
        return parse_xlsx(data)
    if ext in ('odt', 'odp', 'ods'):
        return parse_odf(data, ext)
    handler = {'rtf': parse_rtf, 'epub': parse_epub, 'html': parse_html, 'htm': parse_html, 'doc': parse_doc,
               'ppt': parse_ppt, 'xls': parse_xls}.get(ext)
    if handler is None:
        raise ParseError(f'anydoc does not convert .{ext}')
    return handler(data)
