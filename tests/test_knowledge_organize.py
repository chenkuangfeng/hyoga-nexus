"""Tags, folders, metadata and pinning (openspec 2026-11-06-knowledge-base K5)."""
import pytest
from sqlalchemy import select

from nexus_platform.errors import Conflict, NotFound
from nexus_platform.knowledge import faq, organize, search, service
from nexus_platform.persistence.models import FaqEntryRecord, KnowledgeDocumentRecord

from test_knowledge_service import create_kb, drain, env, find, upload  # noqa: F401 (pytest fixture)
from test_knowledge_faq import add, index, make_faq_kb  # noqa: F401
from test_platform import database  # noqa: F401 (pytest fixture)


def _find(factory, tenant_id, user_id, query, flt):
    import asyncio
    with factory() as db:
        return asyncio.run(search.search(factory, db, tenant_id, user_id, query, doc_filter=flt))


def test_tags_folders_metadata_filter_a_search_but_never_widen_it(env):
    factory, tenant_id, _, owner, member, _ = env
    kb_id = create_kb(factory, tenant_id, owner)
    ids = {}
    for name, text in {'安装.md': '共同词 安装步骤', '报销.md': '共同词 报销流程', '请假.md': '共同词 请假流程'}.items():
        ids[name], _ = upload(factory, tenant_id, owner, kb_id, name, text.encode())
    drain(factory)
    with factory() as db, db.begin():
        tag = organize.create_tag(db, tenant_id, owner, kb_id, name='行政', color='#0052d9')
        tag_id = tag.id
        organize.organize_documents(db, tenant_id, owner, kb_id, [ids['报销.md'], ids['请假.md']],
                                    {'tag_ids': [tag_id], 'folder_path': '制度/人事'})
        organize.organize_documents(db, tenant_id, owner, kb_id, [ids['请假.md']], {'custom_metadata': {'year': '2026'}})
    names = lambda r: sorted(h.filename for h in r.hits)  # noqa: E731
    assert names(find(factory, tenant_id, member, '共同词')) == ['安装.md', '报销.md', '请假.md']
    assert names(_find(factory, tenant_id, member, '共同词', organize.DocumentFilter((str(tag_id),)))) == ['报销.md', '请假.md']
    assert names(_find(factory, tenant_id, member, '共同词', organize.DocumentFilter(folder='制度'))) == ['报销.md', '请假.md']
    assert names(_find(factory, tenant_id, member, '共同词', organize.DocumentFilter(folder='制度', recursive=False))) == []
    assert names(_find(factory, tenant_id, member, '共同词', organize.DocumentFilter(metadata={'year': '2026'}))) == ['请假.md']
    assert names(_find(factory, tenant_id, member, '共同词', organize.DocumentFilter(folder='', recursive=False))) == ['安装.md']
    # A filter naming a tag of another base finds nothing; it cannot reach unreadable content.
    assert names(_find(factory, tenant_id, member, '共同词', organize.DocumentFilter(('00000000-0000-0000-0000-000000000000',)))) == []
    with factory() as db:
        counts = {t['name']: t['knowledge_count'] for t in organize.list_tags(db, tenant_id, member, kb_id)}
        assert counts == {'行政': 2}
        tree = organize.folder_tree(db, tenant_id, member, kb_id)
        assert tree['root_document_count'] == 1 and tree['total_document_count'] == 3
        [root] = tree['folders']
        assert (root['path'], root['total_count'], root['document_count']) == ('制度', 2, 0)
        assert root['children'][0]['path'] == '制度/人事' and root['children'][0]['document_count'] == 2


def test_folder_rename_tag_rules_and_pinning(env):
    factory, tenant_id, _, owner, member, _ = env
    kb_id = create_kb(factory, tenant_id, owner, name='A库')
    other = create_kb(factory, tenant_id, owner, name='B库')
    doc_id, _ = upload(factory, tenant_id, owner, kb_id, 'a.md', '内容'.encode())
    with factory() as db, db.begin():
        tag = organize.create_tag(db, tenant_id, owner, kb_id, name='重要')
        with pytest.raises(Conflict):
            organize.create_tag(db, tenant_id, owner, kb_id, name='重要')
        organize.organize_documents(db, tenant_id, owner, kb_id, [doc_id], {'tag_ids': [tag.id], 'folder_path': '/a/b/'})
        with pytest.raises(ValueError):
            organize.organize_documents(db, tenant_id, owner, kb_id, [doc_id], {'folder_path': '../x'})
        with pytest.raises(NotFound):
            organize.organize_documents(db, tenant_id, owner, kb_id, [doc_id], {'tag_ids': [other]})
        assert organize.rename_folder(db, tenant_id, owner, kb_id, 'a', 'z/y') == 1
        with pytest.raises(ValueError):
            organize.rename_folder(db, tenant_id, owner, kb_id, 'z', 'z/inner')
        with pytest.raises(Conflict):
            organize.delete_tag(db, tenant_id, owner, kb_id, tag.id)
        assert organize.delete_tag(db, tenant_id, owner, kb_id, tag.id, force=True) == 1
    with factory() as db:
        doc = db.get(KnowledgeDocumentRecord, doc_id)
        assert doc.folder_path == 'z/y/b' and doc.tag_ids == []
    with factory() as db, db.begin():
        with pytest.raises(Exception):  # a contributor who is not the creator cannot organize
            organize.create_tag(db, tenant_id, member, kb_id, name='x')
    with factory() as db, db.begin():
        assert organize.toggle_pin(db, tenant_id, owner, other) is True
    with factory() as db:
        assert [b.name for b in service.list_bases(db, tenant_id, owner)] == ['B库', 'A库']


def test_faq_tags_filters_and_category_import(env):
    factory, tenant_id, _, owner, member, _ = env
    kb_id = make_faq_kb(factory, tenant_id, owner)
    with factory() as db, db.begin():
        result = faq.import_entries(db, tenant_id, owner, kb_id, [
            {'standard_question': '如何退货', 'answers': ['七天'], 'category': '售后'},
            {'standard_question': '如何开发票', 'answers': ['在订单页'], 'category': '财务'},
            {'standard_question': '如何换货', 'answers': ['十五天'], 'category': '售后'}], 'append')
    assert result['created'] == 3
    index(factory)
    with factory() as db:
        tags = {t['name']: t for t in organize.list_tags(db, tenant_id, member, kb_id)}
        assert set(tags) == {'售后', '财务'} and tags['售后']['knowledge_count'] == 2
    flt = organize.DocumentFilter((tags['售后']['id'],))
    result = _find(factory, tenant_id, member, '如何', flt)
    assert sorted(h.filename for h in result.hits) == ['如何换货', '如何退货']
    with factory() as db:
        rows, total = faq.list_entries(db, tenant_id, member, kb_id, tag_ids=[tags['财务']['id']])
        assert [r.standard_question for r in rows] == ['如何开发票'] and total == 1


def test_organization_api(env):
    from fastapi.testclient import TestClient
    from nexus_api.dependencies.platform import get_database_session, get_principal
    from nexus_api.main import app
    from test_knowledge_service import OWNER

    factory, tenant_id, _, owner, member, _ = env
    kb_id = create_kb(factory, tenant_id, owner)
    doc_id, _ = upload(factory, tenant_id, owner, kb_id, 'a.md', '内容 文档'.encode())
    drain(factory)

    def session():
        with factory() as db:
            yield db
    app.dependency_overrides[get_database_session] = session
    app.dependency_overrides[get_principal] = lambda: OWNER
    try:
        with TestClient(app) as client:
            base = f'/api/v1/tenants/{tenant_id}/knowledge'
            tag = client.post(f'{base}/bases/{kb_id}/tags', json={'name': '重要', 'color': '#f00'}).json()
            assert client.post(f'{base}/bases/{kb_id}/tags', json={'name': '重要'}).status_code == 409
            assert client.put(f'{base}/document-tags', json={'updates': {str(doc_id): [tag['id']]}}).json()['updated'] == 1
            assert client.patch(f'{base}/bases/{kb_id}/documents', json={'ids': [str(doc_id)], 'folder_path': '手册/第一章'}).json()['updated'] == 1
            listing = client.get(f'{base}/bases/{kb_id}/documents', params={'tag_ids': tag['id'], 'folder_path': '手册'}).json()
            assert listing['total'] == 1 and listing['items'][0]['folder_path'] == '手册/第一章'
            assert client.get(f'{base}/bases/{kb_id}/documents', params={'folder_path': '别处'}).json()['total'] == 0
            tree = client.get(f'{base}/bases/{kb_id}/folders').json()
            assert tree['folders'][0]['path'] == '手册'
            assert client.put(f'{base}/bases/{kb_id}/folders', json={'source': '手册', 'target': '文档'}).json()['moved'] == 1
            found = client.post(f'{base}/search', json={'query': '内容', 'tag_ids': [tag['id']], 'folder_path': '文档'}).json()
            assert [h['filename'] for h in found['items']] == ['a.md']
            assert client.post(f'{base}/search', json={'query': '内容', 'folder_path': '不存在'}).json()['items'] == []
            assert client.put(f'{base}/bases/{kb_id}/pin').json() == {'is_pinned': True}
            assert client.get(f'{base}/bases/{kb_id}').json()['is_pinned'] is True
            assert client.delete(f'{base}/bases/{kb_id}/tags/{tag["id"]}').status_code == 409
            assert client.delete(f'{base}/bases/{kb_id}/tags/{tag["id"]}?force=true').json() == {'removed_from': 1}
    finally:
        app.dependency_overrides.clear()


def test_synonym_groups_widen_the_keyword_query(env):
    from nexus_knowledge.retrieval import synonyms
    assert synonyms.parse([['退货', '退款', '退货'], ['单独'], ['a', 'b']]) == [['退货', '退款'], ['a', 'b']]
    assert synonyms.expand('怎么退货', [['退货', '退款']]) == ['退款'] and synonyms.expand('你好', [['退货', '退款']]) == []
    with pytest.raises(ValueError):
        synonyms.parse('x')
    with pytest.raises(ValueError):
        synonyms.parse([['t'] * 1 + [str(i) for i in range(20)]])
    factory, tenant_id, _, owner, member, _ = env
    kb_id = create_kb(factory, tenant_id, owner, name='同义', settings={'synonyms': [['退货', '退款']]})
    upload(factory, tenant_id, owner, kb_id, 'a.md', '七天内可以申请退款，三个工作日到账'.encode())
    drain(factory)
    assert find(factory, tenant_id, member, '退货').hits  # the document only says 退款
    plain = create_kb(factory, tenant_id, owner, name='无同义')
    upload(factory, tenant_id, owner, plain, 'b.md', '七天内可以申请退款，三个工作日到账'.encode())
    drain(factory)
    with factory() as db:
        import asyncio
        result = asyncio.run(search.search(factory, db, tenant_id, member, '退货', requested=[plain]))
    assert result.hits == []
    with factory() as db, db.begin():
        with pytest.raises(ValueError):
            service.update_base(db, tenant_id, owner, kb_id, {'settings': {'synonyms': 'bad'}})
