"""Knowledge domain: parsing, chunking, fusion and evidence (openspec 2026-11-06-knowledge-base K1.1)."""
import pytest

from nexus_knowledge.evidence import EvidenceRegistry, extract_handles, resolve_citations
from nexus_knowledge.ingest.chunk import chunk_sections, validate
from nexus_knowledge.ingest.parse import (EmptyDocument, Section, UnsupportedDocument, decode_text, parse_document,
                                          parse_markdown)
from nexus_knowledge.retrieval.fuse import Candidate, fuse
from nexus_knowledge.text import query_tokens, tokenize


def _pdf(pages: list[str]) -> bytes:
    """Minimal text PDF with one Helvetica text line per page (ASCII only)."""
    objects = ['<< /Type /Catalog /Pages 2 0 R >>', None, '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>']
    kids = []
    for text in pages:
        stream = f'BT /F1 12 Tf 72 720 Td ({text}) Tj ET'
        objects.append(f'<< /Length {len(stream)} >>\nstream\n{stream}\nendstream')
        content = len(objects)
        objects.append(f'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {content} 0 R '
                       '/Resources << /Font << /F1 3 0 R >> >> >>')
        kids.append(f'{len(objects)} 0 R')
    objects[1] = f'<< /Type /Pages /Kids [{" ".join(kids)}] /Count {len(kids)} >>'
    out, offsets = b'%PDF-1.4\n', []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f'{number} 0 obj\n{body}\nendobj\n'.encode()
    xref = len(out)
    out += f'xref\n0 {len(objects) + 1}\n0000000000 65535 f \n'.encode()
    out += ''.join(f'{offset:010d} 00000 n \n' for offset in offsets).encode()
    out += f'trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n'.encode()
    return out


def test_tokens_are_cjk_bigrams_and_lowercase_words():
    assert tokenize('知识库 RAG检索') == '知识 识库 rag 检索'
    assert query_tokens('检索 检索 abc', limit=2) == ['检索', 'abc']


def test_text_decoding_falls_back_to_gb18030():
    assert decode_text('中文\r\n内容'.encode('gb18030')) == '中文\n内容'
    assert decode_text('﻿hi'.encode('utf-8')) == 'hi'


def test_markdown_sections_carry_the_heading_path_and_ignore_fenced_headings():
    sections = parse_markdown('前言\n# 第一章\n正文一\n## 1.1 小节\n```\n# 不是标题\n```\n# 第二章\n正文二')
    assert [s.section for s in sections] == [(), ('第一章',), ('第一章', '1.1 小节'), ('第二章',)]
    assert '# 不是标题' in sections[2].text


def test_pdf_pages_are_parsed_with_page_numbers():
    sections = parse_document('report.PDF', _pdf(['first page text', '', 'third page text']))
    assert [(s.page, s.text) for s in sections] == [(1, 'first page text'), (3, 'third page text')]


def test_csv_rows_keep_column_names_and_json_is_pretty_printed():
    [table] = parse_document('a.csv', '名称,价格\n苹果,3\n,\n'.encode())
    assert table.text == '名称: 苹果; 价格: 3'
    [data] = parse_document('a.json', b'{"a":1}')
    assert data.text == '{\n  "a": 1\n}'


def test_unsupported_and_empty_documents_fail_with_codes():
    with pytest.raises(UnsupportedDocument) as unsupported:
        parse_document('a.exe', b'x')
    assert unsupported.value.code == 'unsupported_type'
    with pytest.raises(EmptyDocument):
        parse_document('a.txt', b'  \n ')
    with pytest.raises(EmptyDocument):
        parse_document('scan.pdf', _pdf(['']))


def test_chunks_overlap_prefer_sentence_ends_and_keep_positions():
    text = ''.join(f'第{i}句话的内容比较长一些。' for i in range(60))
    chunks = chunk_sections([Section(text, page=2, section=('A',))], size=200, overlap=40)
    assert len(chunks) > 3
    assert all(c.content.endswith('。') for c in chunks[:-1])
    assert all(c.page == 2 and c.section == ('A',) for c in chunks)
    assert [c.ordinal for c in chunks] == list(range(len(chunks)))
    for chunk in chunks:
        assert text[chunk.char_start:chunk.char_end] == chunk.content
    assert chunks[1].char_start < chunks[0].char_end  # overlap


def test_chunks_never_span_sections():
    chunks = chunk_sections([Section('a' * 150, page=1), Section('b' * 150, page=2)], size=200, overlap=0)
    assert [(c.page, set(c.content)) for c in chunks] == [(1, {'a'}), (2, {'b'})]


def test_chunk_parameters_are_validated():
    with pytest.raises(ValueError):
        validate(50, 0)
    with pytest.raises(ValueError):
        validate(800, 400)


def test_fusion_matches_weknora_rules():
    vector = [[Candidate('a', 0.9), Candidate('b', 0.8)]]
    keyword = [[Candidate('b', 12.0), Candidate('c', 6.0)]]
    assert [(f.chunk_id, f.score) for f in fuse(vector, [])] == [('a', 0.9), ('b', 0.8)]
    assert [(f.chunk_id, f.score) for f in fuse([], keyword)] == [('b', 1.0), ('c', 0.5)]
    fused = fuse(vector, keyword)
    assert fused[0].chunk_id == 'b' and fused[0].ranks == {'vector': 2, 'keyword': 1}
    assert all(0 < f.score <= 1 for f in fused)
    both_first = fuse([[Candidate('x', 0.5)]], [[Candidate('x', 3.0)]])
    assert both_first[0].score == pytest.approx(1.0)


def test_fusion_ranks_each_list_on_its_own():
    # Two vector lists (two engines/groups): each list's best hit is rank 1.
    fused = fuse([[Candidate('a', 0.9)], [Candidate('b', 0.4)]], [[Candidate('c', 1.0)]])
    ranks = {f.chunk_id: f.ranks for f in fused}
    assert ranks['a'] == {'vector': 1} and ranks['b'] == {'vector': 1}


def test_evidence_handles_are_stable_and_repeats_are_detected():
    registry = EvidenceRegistry()
    assert registry.serve('c1', 'text one', {'document_id': 'd1'}) == (1, True)
    assert registry.serve('c2', 'text two') == (2, True)
    assert registry.serve('c1', 'text one') == (1, False)
    assert registry.serve('c1', 'other window') == (1, True)
    restored = EvidenceRegistry.from_state(registry.to_state())
    assert restored.serve('c1', 'text one') == (1, False)
    assert restored.stamp('c3') == 3


def test_citations_resolve_only_registered_handles():
    registry = EvidenceRegistry()
    registry.stamp('c1', {'document_id': 'd1', 'page': 4})
    answer = '结论一 [ID:1]。结论二 [ID:7]。再次 [ID:1]'
    assert extract_handles(answer) == [1, 7]
    citations, invalid = resolve_citations(answer, registry)
    assert citations == [{'handle': 1, 'chunk_id': 'c1', 'document_id': 'd1', 'page': 4}]
    assert invalid == [7]


def _zip(files):
    import io
    import zipfile
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        for name, text in files.items():
            archive.writestr(name, text)
    return buffer.getvalue()


_W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def test_docx_headings_paragraphs_and_tables():
    document = (f'<w:document {_W}><w:body>'
                '<w:p><w:pPr><w:pStyle w:val="H1"/></w:pPr><w:r><w:t>第一章</w:t></w:r></w:p>'
                '<w:p><w:r><w:t>正文</w:t></w:r><w:r><w:t>内容</w:t></w:r></w:p>'
                '<w:tbl><w:tr><w:tc><w:p><w:r><w:t>甲</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>乙</w:t></w:r></w:p></w:tc></w:tr></w:tbl>'
                '<w:p><w:pPr><w:pStyle w:val="H1"/></w:pPr><w:r><w:t>第二章</w:t></w:r></w:p><w:p><w:r><w:t>更多</w:t></w:r></w:p>'
                '</w:body></w:document>')
    styles = f'<w:styles {_W}><w:style w:styleId="H1"><w:name w:val="heading 1"/></w:style></w:styles>'
    sections = parse_document('a.docx', _zip({'word/document.xml': document, 'word/styles.xml': styles}))
    assert [s.section for s in sections] == [('第一章',), ('第二章',)]
    assert '正文内容' in sections[0].text and '甲 | 乙' in sections[0].text


def test_pptx_slides_and_xlsx_sheets():
    a = 'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'
    slides = {f'ppt/slides/slide{n}.xml': f'<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" {a}><a:p><a:r><a:t>幻灯片{n}</a:t></a:r></a:p></p:sld>' for n in (2, 1, 10)}
    sections = parse_document('a.pptx', _zip(slides))
    assert [(s.page, s.text) for s in sections] == [(1, '幻灯片1'), (2, '幻灯片2'), (10, '幻灯片10')]
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    rid = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
    files = {
        'xl/workbook.xml': f'<workbook {ns} {rid}><sheets><sheet name="价格" r:id="rId1"/></sheets></workbook>',
        'xl/_rels/workbook.xml.rels': '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                                       '<Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>',
        'xl/sharedStrings.xml': f'<sst {ns}><si><t>名称</t></si><si><t>数量</t></si><si><t>苹果</t></si></sst>',
        'xl/worksheets/sheet1.xml': f'<worksheet {ns}><sheetData><row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c></row>'
                                    '<row r="2"><c r="A2" t="s"><v>2</v></c><c r="B2"><v>3</v></c></row></sheetData></worksheet>'}
    [sheet] = parse_document('a.xlsx', _zip(files))
    assert sheet.section == ('价格',) and sheet.text == '名称: 苹果; 数量: 3'


def test_office_files_reject_dtds_bad_zips_and_non_office_archives():
    from nexus_knowledge.ingest.parse import ParseError
    with pytest.raises(ParseError):
        parse_document('a.docx', b'not a zip')
    with pytest.raises(ParseError):
        parse_document('a.docx', _zip({'word/document.xml': '<!DOCTYPE x [<!ENTITY a "b">]><x/>'}))
    with pytest.raises(ParseError):
        parse_document('a.pptx', _zip({'readme.txt': 'x'}))


def test_chunk_strategies_and_auto_selection():
    from nexus_knowledge.ingest.chunk import ChunkConfig, chunk_document, plan
    headed = parse_markdown('# 一\n' + '内容一。' * 30 + '\n# 二\n' + '内容二。' * 30)
    assert plan(headed, ChunkConfig(size=200, overlap=20)).selected == 'heading'
    slides = [Section(f'幻灯片{i}', page=i) for i in range(1, 6)]
    config = ChunkConfig(size=300, overlap=30)
    assert plan(slides, config).selected == 'heuristic'
    merged = chunk_document(slides, ChunkConfig(size=300, overlap=30, strategy='heuristic'))
    assert len(merged) == 5  # pages differ, so slides are not merged across pages
    same_page = [Section(f'短段{i}', page=1) for i in range(6)]
    assert len(chunk_document(same_page, ChunkConfig(size=300, overlap=30, strategy='heuristic'))) == 1
    plain = [Section('一个很长的段落。' * 80)]
    assert plan(plain, config).selected == 'recursive'
    legacy = chunk_document([Section('a' * 250), Section('b' * 250)], ChunkConfig(size=200, overlap=0, strategy='legacy'))
    assert all(len(c.content) <= 200 for c in legacy) and len(legacy) >= 3
    custom = chunk_document([Section('甲|乙|丙|' * 40)], ChunkConfig(size=100, overlap=0, strategy='recursive', separators=('|',)))
    assert all(c.content.endswith('|') or c is custom[-1] for c in custom)


def test_parent_child_chunks_index_children_only():
    from nexus_knowledge.ingest.chunk import ChunkConfig, chunk_document
    config = ChunkConfig(size=200, overlap=0, strategy='recursive', parent_child=True, parent_size=600, child_size=150)
    chunks = chunk_document([Section('句子内容。' * 400)], config)
    parents = [c for c in chunks if not c.indexed]
    children = [c for c in chunks if c.indexed]
    assert parents and children and all(c.parent is not None for c in children) and all(c.parent is None for c in parents)
    assert [c.ordinal for c in chunks] == list(range(len(chunks)))
    assert all(len(c.content) <= 150 for c in children) and all(len(p.content) <= 600 for p in parents)
    for child in children:
        assert child.content in chunks[child.parent].content
    with pytest.raises(ValueError):
        ChunkConfig(parent_child=True, parent_size=300, child_size=300).validate()
    with pytest.raises(ValueError):
        ChunkConfig(strategy='bogus').validate()


def test_chunk_preview_reports_strategy_and_statistics():
    from nexus_knowledge.ingest.chunk import ChunkConfig, preview
    result = preview(parse_markdown('# 甲\n' + '正文。' * 80 + '\n# 乙\n' + '正文。' * 80), ChunkConfig(size=200, overlap=20))
    assert result['selected_tier'] == 'heading' and result['stats']['count'] == len(result['chunks'])
    assert result['chunks'][0]['context_header'] == '甲' and result['stats']['max_chars'] <= 200
