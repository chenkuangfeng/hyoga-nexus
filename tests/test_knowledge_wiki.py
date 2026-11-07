"""Wiki knowledge bases: synthesis, pages, revisions, directory, search (openspec 2026-11-06-knowledge-base K6)."""
import json
from uuid import uuid4

import pytest
from sqlalchemy import select

from nexus_knowledge.wiki import rules
from nexus_platform.errors import Conflict, Forbidden, NotFound
from nexus_platform.knowledge import service, wiki, wiki_ingest
from nexus_platform.knowledge.graph import llm
from nexus_platform.persistence.models import KnowledgeJobRecord, WikiFolderRecord, WikiPageRecord, WikiRevisionRecord

from test_knowledge_service import drain, env, find, run, upload  # noqa: F401 (pytest fixture)
from test_platform import database  # noqa: F401 (pytest fixture)

DOC = '# 星河科技\n星河科技是一家做检索增强生成（RAG）产品的公司。\n\n检索增强生成把检索与大模型结合。星河科技的旗舰产品使用它。'


class Scripted:
    """Answers each Wiki prompt by its system/user text; records the kinds of calls."""

    def __init__(self):
        self.calls: list[str] = []
        self.entities = [{'name': '星河科技', 'slug': 'entity/xinghe', 'aliases': ['Xinghe'], 'description': '一家做 RAG 的公司。',
                          'details': '星河科技做 RAG 产品。'}]
        self.concepts = [{'name': '检索增强生成', 'slug': 'concept/rag', 'aliases': ['RAG'], 'description': '检索加生成。',
                          'details': '把检索与大模型结合。'}]
        self.merge: dict[str, str] = {}

    async def __call__(self, factory, tenant, user, model, purpose, system, text, max_tokens):
        if 'extract knowledge' in system:
            self.calls.append('extract')
            return json.dumps({'entities': self.entities, 'concepts': self.concepts}, ensure_ascii=False)
        if 'deduplication' in system:
            self.calls.append('dedup')
            return json.dumps({'merges': self.merge})
        if 'organize a wiki directory' in system:
            self.calls.append('taxonomy')
            return json.dumps({'assignments': [{'slug': 'entity/xinghe', 'path': ['组织']},
                                               {'slug': 'concept/rag', 'path': ['技术', '检索']}]}, ensure_ascii=False)
        if 'wiki editor tasked' in system:
            self.calls.append('page')
            slug = text.split('<slug>')[1].split('</slug>')[0]
            link = '[[concept/rag|检索增强生成]] [[nowhere|不存在]]' if slug == 'entity/xinghe' else '[[entity/xinghe|星河科技]]'
            return f'SUMMARY: 页面 {slug} 的摘要，描述它是什么。\n# 页面\n正文 {link}'
        if 'wiki summary page' in text:
            self.calls.append('summary')
            return 'SUMMARY: 介绍星河科技与 RAG 的文档。\n## 概述\n[[entity/xinghe|星河科技]] 做 [[concept/rag|RAG]]。'
        self.calls.append('intro')
        return '# 星河知识库\n收录星河科技与 RAG。'


@pytest.fixture
def wikis(env, monkeypatch):
    factory, tenant_id, _, owner, member, _ = env
    monkeypatch.setattr(service, '_authorize_chat_model', lambda *args: None)
    model = Scripted()
    llm.set_completer(model)
    settings = {'wiki_config': {'synthesis_model_id': str(uuid4()), 'extraction_granularity': 'standard'}}
    with factory() as db, db.begin():
        kb = service.create_base(db, tenant_id, owner, name='星河', kb_type='wiki', settings=settings,
                                 indexing={'vector': False, 'keyword': True})
        kb_id = kb.id
        assert kb.indexing['wiki'] is True
    yield factory, tenant_id, owner, member, kb_id, model
    llm.set_completer(None)


def pump(factory):
    drain(factory)
    while run(wiki_ingest.index_tick(factory)):
        pass


def test_rules():
    assert rules.normalize_slug(' Entity/Zhang  San! ') == 'entity/zhang-san'
    assert rules.extract_links('a [[entity/x|X]] b [[Entity/X]] [[y]]') == ['entity/x', 'y']
    assert rules.sanitize_links('[[a|A]] [[b|B]] [[me|M]]', {'a', 'me'}, 'me') == '[[a|A]] B M'
    assert rules.clean_category_path(['A/B', 'A B', 'C', 'D']) == ['A B', 'C']
    assert rules.split_summary('\nSUMMARY: s\n# t') == ('s', '# t')
    items = rules.parse_extraction('```json\n{"entities":[{"name":"A","slug":"a"}],"concepts":[{"name":"A","slug":"concept/a"}]}\n```')
    assert [i.slug for i in items] == ['entity/a', 'concept/a']
    item = rules.Extracted('entity', 'Acme Corp', 'entity/acme-corp', ['Acme'])
    assert rules.similar_pages(item, [('entity/acme', 'Acme', []), ('concept/acme', 'Acme', []), ('entity/zzz', 'Other', [])]) == ['entity/acme']
    assert rules.parse_merges('{"merges":{"entity/n":"entity/o","entity/m":"concept/o"}}', {'entity/n', 'entity/m'},
                              {'entity/n': {'entity/o'}, 'entity/m': {'concept/o'}}) == {'entity/n': 'entity/o'}


def test_ingest_builds_pages_links_folders_and_index(wikis):
    factory, tenant_id, owner, member, kb_id, model = wikis
    doc_id, _ = upload(factory, tenant_id, owner, kb_id, '星河.md', DOC.encode())
    pump(factory)
    assert model.calls.count('extract') == 1 and model.calls.count('summary') == 1 and model.calls.count('taxonomy') == 1
    with factory() as db:
        pages = {p.slug: p for p in db.scalars(select(WikiPageRecord))}
        assert set(pages) >= {'entity/xinghe', 'concept/rag', 'index'} and any(s.startswith('summary/') for s in pages)
        entity = pages['entity/xinghe']
        assert 'nowhere' not in entity.content and '不存在' in entity.content  # link to an unknown page is dropped
        assert entity.out_links == ['concept/rag'] and 'concept/rag' in entity.in_links
        assert any(link.startswith('summary/') for link in entity.in_links)  # the summary page links its entities
        assert entity.source_refs == [str(doc_id)] and entity.aliases == ['Xinghe']
        assert entity.category_path == ['组织'] and pages['concept/rag'].category_path == ['技术', '检索']
        assert {f.path for f in db.scalars(select(WikiFolderRecord))} == {'组织', '技术', '技术/检索'}
        assert pages['index'].content.startswith('# 星河知识库')
        assert all(p.index_state == 'ready' for p in pages.values() if p.page_type != 'index')
    # Wiki pages are found by the normal search (summary line + names are indexed) and come with their slug.
    hits = find(factory, tenant_id, member, 'Xinghe').hits
    assert hits and hits[0].filename == 'Wiki · 星河科技' and 'entity/xinghe' in hits[0].content
    # A document hit and a page hit can coexist.
    assert any(h.filename == '星河.md' for h in find(factory, tenant_id, member, '旗舰产品').hits)


def test_dedup_merges_into_existing_page_and_retraction(wikis):
    factory, tenant_id, owner, member, kb_id, model = wikis
    first, _ = upload(factory, tenant_id, owner, kb_id, 'a.md', DOC.encode())
    pump(factory)
    model.entities = [{'name': '星河科技有限公司', 'slug': 'entity/xinghe-co', 'aliases': ['星河'], 'description': 'd', 'details': 'x'}]
    model.concepts = []
    model.merge = {'entity/xinghe-co': 'entity/xinghe'}
    second, _ = upload(factory, tenant_id, owner, kb_id, 'b.md', '# 星河科技有限公司\n星河科技有限公司成立于 2020 年。'.encode())
    pump(factory)
    assert 'dedup' in model.calls
    with factory() as db:
        page = db.scalar(select(WikiPageRecord).where(WikiPageRecord.slug == 'entity/xinghe'))
        assert page.source_refs == [str(first), str(second)] and page.version == 2
        assert {'星河科技有限公司', '星河', 'Xinghe'} <= set(page.aliases) | {page.title}
        assert db.scalar(select(WikiPageRecord).where(WikiPageRecord.slug == 'entity/xinghe-co')) is None
        assert db.scalar(select(WikiRevisionRecord).where(WikiRevisionRecord.page_id == page.id)).version == 1
    # Deleting the first document removes its summary and the concept only it supported; the shared page is rewritten.
    with factory() as db, db.begin():
        service.delete_document(db, tenant_id, owner, first)
    model.calls.clear()
    pump(factory)
    with factory() as db:
        slugs = {p.slug for p in db.scalars(select(WikiPageRecord))}
        assert 'concept/rag' not in slugs and 'entity/xinghe' in slugs and len([s for s in slugs if s.startswith('summary/')]) == 1
        page = db.scalar(select(WikiPageRecord).where(WikiPageRecord.slug == 'entity/xinghe'))
        assert page.source_refs == [str(second)] and 'concept/rag' not in page.out_links or 'rag' not in page.content.lower()
    assert not find(factory, tenant_id, member, 'RAG').hits or all('concept/rag' not in h.content for h in find(factory, tenant_id, member, 'RAG').hits)


def test_page_api_revisions_folders_and_permissions(wikis):
    factory, tenant_id, owner, member, kb_id, _ = wikis
    with factory() as db, db.begin():
        created = wiki.create_page(db, tenant_id, owner, kb_id, {'title': '退货流程', 'content': '先 [[faq]] 后退款', 'page_type': 'concept',
                                                                 'category_path': ['售后']})
    slug = created['slug']
    assert slug == 'concept/退货流程' and created['version'] == 1 and created['folder_id']
    with factory() as db, db.begin():
        wiki.create_page(db, tenant_id, owner, kb_id, {'title': 'FAQ', 'slug': 'faq', 'page_type': 'synthesis', 'content': '常见问题'})
        updated = wiki.update_page(db, tenant_id, owner, kb_id, slug, {'content': '改后 [[faq|FAQ]]', 'version': 1})
    assert updated['version'] == 2 and updated['out_links'] == ['faq']
    with factory() as db, db.begin():
        with pytest.raises(Conflict):
            wiki.update_page(db, tenant_id, owner, kb_id, slug, {'content': 'x', 'version': 1})
    with factory() as db, db.begin():
        assert wiki.get_page(db, tenant_id, owner, kb_id, 'faq')['in_links'] == [slug]
        revs = wiki.list_revisions(db, tenant_id, owner, kb_id, slug)
        assert [r['version'] for r in revs['revisions']] == [1] and revs['current_version'] == 2
        assert wiki.get_revision(db, tenant_id, owner, kb_id, slug, 1)['content'].startswith('先')
        reverted = wiki.revert_page(db, tenant_id, owner, kb_id, slug, 1)
        assert reverted['version'] == 3 and reverted['content'].startswith('先') and reverted['last_edit_source'] == 'revert'
    with factory() as db, db.begin():
        tree = wiki.list_folders(db, tenant_id, owner, kb_id)['folders']
        assert [(f['name'], f['page_count']) for f in tree] == [('售后', 1)]
        folder = wiki.create_folder(db, tenant_id, owner, kb_id, tree[0]['id'], '子')
        moved = wiki.move_page(db, tenant_id, owner, kb_id, slug, folder['id'])
        assert moved['category_path'] == ['售后', '子']
        wiki.update_folder(db, tenant_id, owner, kb_id, __import__('uuid').UUID(tree[0]['id']), {'name': '客服'})
        assert wiki.get_page(db, tenant_id, owner, kb_id, slug)['category_path'] == ['客服', '子']
        with pytest.raises(Conflict):
            wiki.delete_folder(db, tenant_id, owner, kb_id, __import__('uuid').UUID(tree[0]['id']))
        graph = wiki.get_graph(db, tenant_id, owner, kb_id)
        assert {(e['source'], e['target']) for e in graph['edges']} == {(slug, 'faq')}  # the reverted text links to the existing faq page
        assert wiki.get_index(db, tenant_id, owner, kb_id)['groups'][0]['type'] == 'summary'
        assert wiki.search_pages(db, tenant_id, owner, kb_id, '退货')['pages'][0]['slug'] == slug
        result = wiki.lint(db, tenant_id, owner, kb_id)
        assert result['new_issues'] >= 1
        issue = wiki.list_issues(db, tenant_id, owner, kb_id)[0]
        assert wiki.set_issue_status(db, tenant_id, owner, kb_id, __import__('uuid').UUID(issue['id']), 'resolved')['status'] == 'resolved'
        assert wiki.get_stats(db, tenant_id, owner, kb_id)['total_pages'] == 2
    # Members may read but not change; deleting hides the page at once and the worker removes it.
    with factory() as db, db.begin():
        assert wiki.list_pages(db, tenant_id, member, kb_id)['total'] == 2
        with pytest.raises(Forbidden):
            wiki.update_page(db, tenant_id, member, kb_id, slug, {'content': 'x'})
        wiki.delete_page(db, tenant_id, owner, kb_id, 'faq')
        with pytest.raises(NotFound):
            wiki.get_page(db, tenant_id, owner, kb_id, 'faq')
    pump(factory)
    with factory() as db:
        assert db.scalar(select(WikiPageRecord).where(WikiPageRecord.slug == 'faq')) is None


def test_wiki_needs_model_and_backfills_existing_documents(env, monkeypatch):
    factory, tenant_id, _, owner, _, _ = env
    monkeypatch.setattr(service, '_authorize_chat_model', lambda *args: None)
    llm.set_completer(Scripted())
    try:
        with factory() as db, db.begin():
            kb_id = service.create_base(db, tenant_id, owner, name='普通', indexing={'vector': False, 'keyword': True}).id
        upload(factory, tenant_id, owner, kb_id, 'a.md', DOC.encode())
        drain(factory)
        with factory() as db, db.begin():
            with pytest.raises(ValueError, match='synthesis model'):
                service.update_base(db, tenant_id, owner, kb_id, {'indexing_strategy': {'keyword': True, 'vector': False, 'wiki': True}})
            service.update_base(db, tenant_id, owner, kb_id, {
                'indexing_strategy': {'keyword': True, 'vector': False, 'wiki': True},
                'settings': {'wiki_config': {'synthesis_model_id': str(uuid4())}}})
            db.flush()
            assert db.scalar(select(KnowledgeJobRecord).where(KnowledgeJobRecord.kind == 'wiki')) is not None
        pump(factory)
        with factory() as db:
            assert db.scalar(select(WikiPageRecord).where(WikiPageRecord.slug == 'entity/xinghe')) is not None
    finally:
        llm.set_completer(None)


def test_wiki_http_api(database, deployment_config, tmp_path, monkeypatch):
    from cryptography.fernet import Fernet
    from fastapi.testclient import TestClient

    from nexus_api.dependencies.platform import get_database_session, get_principal
    from nexus_api.main import app
    from nexus_core.platform import Principal
    from nexus_platform.tenants.service import create_tenant

    deployment_config(f'[security]\ncredential_encryption_key = "{Fernet.generate_key().decode()}"\n'
                      f'[knowledge]\ndata_dir = "{tmp_path / "k"}"\n')
    owner = Principal('wiki-api-owner', 'test')
    with database() as db:
        tenant = create_tenant(db, owner, 'Wiki API')

    def session():
        with database() as db:
            yield db
    monkeypatch.setattr(service, '_authorize_chat_model', lambda *args: None)
    app.dependency_overrides[get_database_session] = session
    app.dependency_overrides[get_principal] = lambda: owner
    try:
        with TestClient(app) as client:
            base = f'/api/v1/tenants/{tenant.id}/knowledge'
            plain = client.post(base + '/bases', json={'name': '普通', 'indexing_strategy': {'vector': False, 'keyword': True}}).json()
            assert client.get(f'{base}/bases/{plain["id"]}/wiki/pages').status_code == 404  # wiki is not enabled
            missing = client.post(base + '/bases', json={'name': 'w0', 'type': 'wiki', 'indexing_strategy': {'vector': False, 'keyword': True}})
            assert missing.status_code == 422
            kb = client.post(base + '/bases', json={
                'name': 'w', 'type': 'wiki', 'indexing_strategy': {'vector': False, 'keyword': True},
                'settings': {'wiki_config': {'synthesis_model_id': str(uuid4())}}})
            assert kb.status_code == 201, kb.text
            wiki_path = f'{base}/bases/{kb.json()["id"]}/wiki'
            created = client.post(wiki_path + '/pages', json={'title': '甲', 'content': '正文', 'page_type': 'entity'})
            assert created.status_code == 201 and created.json()['slug'] == 'entity/甲'
            page = client.get(wiki_path + '/pages/entity/甲').json()
            assert page['version'] == 1
            stale = client.put(wiki_path + '/pages/entity/甲', json={'content': 'x', 'version': 7})
            assert stale.status_code == 409 and stale.json()['current_version'] == 1
            assert client.put(wiki_path + '/pages/entity/甲', json={'content': '新', 'version': 1}).json()['version'] == 2
            assert client.get(wiki_path + '/revisions/entity/甲').json()['current_version'] == 2
            assert client.get(wiki_path + '/revisions/entity/甲?version=1').json()['content'] == '正文'
            assert client.post(wiki_path + '/revert', json={'slug': 'entity/甲', 'version': 1}).json()['version'] == 3
            assert client.get(wiki_path + '/stats').json()['total_pages'] == 1
            assert client.get(wiki_path + '/search?q=甲').json()['total'] == 1
            assert client.get(wiki_path + '/graph').json()['nodes'][0]['slug'] == 'entity/甲'
            assert client.get(wiki_path + '/index').json()['groups'][0]['type'] == 'summary'
            assert client.get(wiki_path + '/folders').json()['folders'] == []
            assert client.post(wiki_path + '/rebuild-links').json() == {'pages': 1}
            assert client.delete(wiki_path + '/pages/entity/甲').status_code == 204
            assert client.get(wiki_path + '/pages/entity/甲').status_code == 404
    finally:
        app.dependency_overrides.clear()
