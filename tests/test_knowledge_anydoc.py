"""In-process office / ebook conversion (the ``anydoc`` engine), checked against the fixtures WeKnora tests with."""
from pathlib import Path

import pytest

from nexus_knowledge.ingest import anydoc
from nexus_knowledge.ingest.parse import ParseError
from nexus_platform.knowledge import parsers

from test_knowledge_service import create_kb, drain, env, find, upload  # noqa: F401 (pytest fixture)
from test_platform import database  # noqa: F401 (pytest fixture)

FIXTURES = Path(__file__).parent / 'fixtures' / 'office'


def sections(name):
    path = FIXTURES / name
    return anydoc.parse(path.suffix, path.read_bytes())


def text_of(name):
    return '\n'.join(s.text for s in sections(name))


def test_legacy_word_document_text_comes_out_in_order():
    text = text_of('text.doc')
    assert text.startswith('Fixture Document\nPlain paragraph with bold, italic, and struck runs.')
    assert 'First numbered' in text and 'Alpha sub one' in text and '\x13' not in text and '\x07' not in text


def test_legacy_powerpoint_slides_become_pages():
    slides = sections('pres.ppt')
    assert [s.page for s in slides] == [1, 2] and 'Deck Title Slide' in slides[0].text
    assert 'Nested detail' in slides[0].text


def test_legacy_excel_sheets_keep_headers_and_integers():
    by_name = {s.section[0]: s.text for s in sections('sheet.xls')}
    assert set(by_name) == {'Values', 'Merged Grid'}
    assert 'Kind: Currency; Value: 1234.5; Note: dollars' in by_name['Values']
    assert 'Value: 9876543;' in by_name['Values']  # a whole float is shown as an integer


def test_rtf_text_with_unicode_and_skipped_groups():
    text = text_of('text.rtf')
    assert text.startswith('Fixture Document') and 'Plain paragraph with bold, italic, and struck runs.' in text
    assert 'Times New Roman' not in text and '\\' not in text  # font table and control words are gone
    assert 'A price of $5 or $6 is not math.' in text_of('handmade-math.rtf')


def test_opendocument_text_slides_and_sheets():
    odt = sections('text.odt')
    assert odt[0].section == ('Fixture Document',) and any(s.section == ('Fixture Document', 'Lists') for s in odt)
    assert [s.page for s in sections('pres.odp')] == [1, 2]
    assert 'Value: 15.5%' in sections('sheet.ods')[0].text


def test_epub_chapters_follow_the_spine():
    book = sections('book.epub')
    assert [s.section[0] for s in book] == ['Fixture Book', 'Chapter One', 'Chapter Two']


def test_html_becomes_headed_sections_without_scripts():
    html = ('<html><head><title>t</title><script>alert(1)</script></head><body><h1>总览</h1><p>第一段</p>'
            '<h2>细节</h2><ul><li>要点一</li></ul><table><tr><td>甲</td><td>乙</td></tr></table></body></html>')
    result = anydoc.parse('.html', html.encode())
    assert [s.section for s in result] == [('总览',), ('总览', '细节')]
    assert 'alert' not in '\n'.join(s.text for s in result) and '甲 | 乙' in result[1].text


def test_broken_files_raise_parse_errors_not_crashes():
    for suffix in ('.doc', '.ppt', '.xls', '.rtf', '.epub', '.odt', '.docx'):
        with pytest.raises(ParseError):
            anydoc.parse(suffix, b'this is not a real document')
    with pytest.raises(ParseError):
        anydoc.parse('.exe', b'x')


def test_engine_choice_prefers_anydoc_for_formats_builtin_cannot_read():
    assert parsers.engine_for(None, 'a.doc') == 'anydoc' and parsers.engine_for(None, 'a.epub') == 'anydoc'
    assert parsers.engine_for(None, 'a.md') == 'builtin' and parsers.engine_for(None, 'a.docx') == 'builtin'
    rule = {'chunking_config': {'parser_engine_rules': [{'file_types': ['doc'], 'engine': 'builtin'}]}}
    assert parsers.engine_for(rule, 'a.doc') == 'builtin'  # an explicit rule wins


def test_uploaded_legacy_and_ebook_files_are_searchable(env):
    factory, tenant_id, _, owner, member, _ = env
    kb_id = create_kb(factory, tenant_id, owner, name='办公文档')
    for name in ('text.doc', 'pres.ppt', 'sheet.xls', 'text.rtf', 'book.epub', 'pres.odp'):
        upload(factory, tenant_id, owner, kb_id, name, (FIXTURES / name).read_bytes())
    drain(factory)
    assert find(factory, tenant_id, member, 'Plain paragraph').hits[0].filename in ('text.doc', 'text.rtf')
    assert find(factory, tenant_id, member, 'Deck Title Slide').hits
    assert find(factory, tenant_id, member, 'dollars').hits[0].filename == 'sheet.xls'
    assert find(factory, tenant_id, member, 'Chapter').hits[0].filename == 'book.epub'
