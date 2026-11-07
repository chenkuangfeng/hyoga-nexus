"""External parser engines through mock transports (openspec 2026-11-06-knowledge-base K4).

Protocol shapes follow WeKnora's converters; the real services are not exercised here.
"""
import asyncio
import base64
import io
import json
import zipfile

import httpx
import pytest
from fastapi.testclient import TestClient

from nexus_api.dependencies.platform import get_database_session, get_principal
from nexus_api.main import app
from nexus_knowledge.ingest import engines
from nexus_knowledge.ingest.parse import ParseError
from nexus_platform.knowledge import parsers, service

from test_knowledge_service import OWNER, drain, env, find, upload  # noqa: F401 (pytest fixture)
from test_platform import database  # noqa: F401 (pytest fixture)


def factory_for(handler):
    return lambda url: httpx.AsyncClient(transport=httpx.MockTransport(handler))


def run(coro):
    return asyncio.run(coro)


def test_markdown_cleanup_drops_local_images_only():
    text = '# 标题\n\\# 转义标题\n![图](images/a.jpg) 保留 ![远程](https://x.test/a.png)'
    cleaned = engines.clean_markdown(text)
    assert 'images/a.jpg' not in cleaned and 'https://x.test/a.png' in cleaned and '\n# 转义标题' in cleaned
    sections = engines.to_sections('# 一\n甲\n# 二\n乙')
    assert [s.section for s in sections] == [('一',), ('二',)]


def test_mineru_self_hosted_posts_multipart_and_reads_markdown():
    seen = {}

    def handler(request):
        seen['path'] = request.url.path
        seen['body'] = request.content
        seen['auth'] = request.headers.get('authorization')
        return httpx.Response(200, json={'results': {'报告': {'md_content': '# 报告\n正文'}}})

    config = {'mineru_endpoint': 'http://mineru.test:8000/', 'mineru_server_api_key': 'k', 'mineru_language': 'en'}
    markdown = run(engines.mineru(factory_for(handler), config, '报告.pdf', b'%PDF'))
    assert markdown == '# 报告\n正文' and seen['path'] == '/file_parse' and seen['auth'] == 'Bearer k'
    assert b'name="lang_list"' in seen['body'] and b'en' in seen['body'] and b'%PDF' in seen['body']
    empty = run(engines.mineru(factory_for(lambda r: httpx.Response(200, json={'results': {}})), config, 'a.pdf', b'x'))
    assert empty == ''
    with pytest.raises(engines.EngineError, match='HTTP 500'):
        run(engines.mineru(factory_for(lambda r: httpx.Response(500, text='boom')), config, 'a.pdf', b'x'))


def test_mineru_cloud_flow_uploads_polls_and_reads_the_zip():
    calls = []
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, 'w') as z:
        z.writestr('out/full.md', '# 云端结果\n内容')
    polls = {'n': 0}

    def handler(request):
        calls.append((request.method, request.url.host, request.url.path))
        if request.url.path.endswith('/file-urls/batch'):
            assert request.headers['authorization'] == 'Bearer tok'
            return httpx.Response(200, json={'code': 0, 'data': {'batch_id': 'b1', 'file_urls': ['https://oss.test/up']}})
        if request.method == 'PUT':
            return httpx.Response(200)
        if '/extract-results/batch/b1' in request.url.path:
            polls['n'] += 1
            state = 'running' if polls['n'] == 1 else 'done'
            return httpx.Response(200, json={'code': 0, 'data': {'extract_result': [
                {'state': state, 'full_zip_url': 'https://cdn.test/r.zip'}]}})
        return httpx.Response(200, content=archive.getvalue())

    markdown = run(engines.mineru_cloud(factory_for(handler), {'mineru_api_key': 'tok'}, 'a.pdf', b'%PDF',
                                        poll_interval=0.0))
    assert markdown == '# 云端结果\n内容' and polls['n'] == 2
    assert ('PUT', 'oss.test', '/up') in calls and any(c[1] == 'cdn.test' for c in calls)

    failed = lambda r: httpx.Response(200, json={'code': 0, 'data': {  # noqa: E731
        'batch_id': 'b', 'file_urls': ['https://oss.test/u'], 'extract_result': [{'state': 'failed', 'err_msg': 'bad pdf'}]}})
    with pytest.raises(engines.EngineError, match='bad pdf'):
        run(engines.mineru_cloud(factory_for(failed), {'mineru_api_key': 't'}, 'a.pdf', b'x', poll_interval=0.0))


def test_paddleocr_self_hosted_and_cloud():
    seen = {}

    def local(request):
        seen['body'] = json.loads(request.content)
        return httpx.Response(200, json={'errorCode': 0, 'result': {'layoutParsingResults': [
            {'markdown': {'text': '第一页'}}, {'markdown': {'text': '第二页'}}]}})

    markdown = run(engines.paddleocr_vl(factory_for(local), {'paddleocr_vl_endpoint': 'http://p.test'}, 'a.pdf', b'PDF'))
    assert markdown == '第一页\n\n第二页' and seen['body']['fileType'] == 0
    assert base64.b64decode(seen['body']['file']) == b'PDF' and seen['body']['useLayoutDetection'] is True
    error = lambda r: httpx.Response(200, json={'errorCode': 5, 'errorMsg': 'overloaded'})  # noqa: E731
    with pytest.raises(engines.EngineError, match='overloaded'):
        run(engines.paddleocr_vl(factory_for(error), {'paddleocr_vl_endpoint': 'http://p.test'}, 'a.png', b'x'))

    def cloud(request):
        if request.method == 'POST':
            assert request.headers['authorization'] == 'bearer t'
            return httpx.Response(200, json={'data': {'jobId': 'j1'}})
        if request.url.path.endswith('/j1'):
            return httpx.Response(200, json={'data': {'state': 'done', 'resultUrl': {'jsonUrl': 'https://r.test/j.jsonl'}}})
        line = json.dumps({'result': {'layoutParsingResults': [{'markdown': {'text': '云端文字'}}]}})
        return httpx.Response(200, text=line + '\n\n' + line)

    assert run(engines.paddleocr_vl_cloud(factory_for(cloud), {'paddleocr_vl_cloud_token': 't'}, 'a.png', b'x',
                                          poll_interval=0.0)) == '云端文字\n\n云端文字'


def test_unconfigured_or_unknown_engines_fail_clearly():
    with pytest.raises(engines.EngineError, match='not configured'):
        run(engines.parse_with('mineru', factory_for(lambda r: httpx.Response(200)), {}, 'a.pdf', b'x'))
    with pytest.raises(engines.EngineError, match='unknown'):
        run(engines.parse_with('nope', factory_for(lambda r: httpx.Response(200)), {}, 'a.pdf', b'x'))
    with pytest.raises(ParseError, match='no text'):
        run(engines.parse_with('mineru', factory_for(lambda r: httpx.Response(200, json={'results': {}})),
                               {'mineru_endpoint': 'http://m.test'}, 'a.pdf', b'x'))


def test_rules_pick_an_engine_per_file_type():
    settings = {'chunking_config': {'parser_engine_rules': [{'file_types': ['.PDF', 'docx'], 'engine': 'mineru'}]}}
    assert parsers.engine_for(settings, '报告.pdf') == 'mineru' and parsers.engine_for(settings, 'a.docx') == 'mineru'
    assert parsers.engine_for(settings, 'a.md') == 'builtin' and parsers.engine_for(None, 'a.pdf') == 'builtin'


def test_a_base_with_a_rule_parses_through_the_engine(env, monkeypatch):
    factory, tenant_id, _, owner, member, _ = env
    from cryptography.fernet import Fernet
    from pathlib import Path
    config_file = Path('configs/nexus.toml')
    config_file.write_text(config_file.read_text() + f'\n[security]\ncredential_encryption_key = "{Fernet.generate_key().decode()}"\n')
    with factory() as db, db.begin():
        parsers.save_config(db, tenant_id, owner, {'mineru_endpoint': 'http://mineru.test', 'mineru_api_key': 'secret-token'})
    with factory() as db:
        assert parsers.masked_config(db, tenant_id, owner)['mineru_api_key'] == '******'
        assert parsers.load_config(db, tenant_id)['mineru_api_key'] == 'secret-token'
    handler = lambda r: httpx.Response(200, json={'results': {'a': {'md_content': '# 扫描报告\n季度营收增长'}}})  # noqa: E731
    parsers.set_http_client_factory(factory_for(handler))
    try:
        with factory() as db, db.begin():
            kb_id = service.create_base(db, tenant_id, owner, name='引擎', indexing={'vector': False, 'keyword': True},
                                        settings={'chunking_config': {'parser_engine_rules': [
                                            {'file_types': ['pdf'], 'engine': 'mineru'}]}}).id
        upload(factory, tenant_id, owner, kb_id, 'a.pdf', b'%PDF-1.4 bytes the engine reads')
        drain(factory)
        hit = find(factory, tenant_id, member, '季度营收').hits[0]
        assert hit.filename == 'a.pdf' and hit.section == ['扫描报告']
    finally:
        parsers.set_http_client_factory(None)


def test_parser_config_api_is_admin_only_and_lists_engines(env):
    factory, tenant_id, _, owner, member, _ = env
    from cryptography.fernet import Fernet
    from pathlib import Path
    config_file = Path('configs/nexus.toml')
    config_file.write_text(config_file.read_text() + f'\n[security]\ncredential_encryption_key = "{Fernet.generate_key().decode()}"\n')

    def session():
        with factory() as db:
            yield db
    who = [OWNER]
    app.dependency_overrides[get_database_session] = session
    app.dependency_overrides[get_principal] = lambda: who[0]
    try:
        with TestClient(app) as client:
            base = f'/api/v1/tenants/{tenant_id}/knowledge'
            listed = {e['Name']: e for e in client.get(f'{base}/parser-engines').json()['data']}
            assert listed['mineru']['Available'] is False and 'mineru_endpoint' in listed['mineru']['UnavailableReason']
            assert listed['builtin']['Available'] and listed['anydoc']['Available'] and listed['markitdown']['UnavailableReason'].startswith('待实现')
            saved = client.put(f'{base}/parser-engine-config', json={'mineru_endpoint': 'http://m.test',
                                                                      'mineru_api_key': 'abc'}).json()['data']
            assert saved['mineru_api_key'] == '******'
            listed = {e['Name']: e for e in client.get(f'{base}/parser-engines').json()['data']}
            assert listed['mineru']['Available'] is True
            kept = client.put(f'{base}/parser-engine-config', json={'mineru_endpoint': 'http://m2.test',
                                                                     'mineru_api_key': '******'}).json()['data']
            assert kept['mineru_endpoint'] == 'http://m2.test'
            assert client.put(f'{base}/parser-engine-config', json={'bogus': 1}).status_code == 422
            who[0] = type(OWNER)('kb-member', 'test')
            assert client.put(f'{base}/parser-engine-config', json={}).status_code == 403
    finally:
        app.dependency_overrides.clear()
