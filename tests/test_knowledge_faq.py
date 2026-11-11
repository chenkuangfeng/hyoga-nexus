"""FAQ knowledge bases on SQLite (openspec 2026-11-06-knowledge-base K3)."""
import asyncio

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from nexus_api.dependencies.platform import get_database_session, get_principal
from nexus_api.main import app
from nexus_platform.errors import Conflict
from nexus_platform.knowledge import embedding, faq, service
from nexus_platform.persistence.models import FaqEntryRecord

from test_knowledge_service import OWNER, env, find  # noqa: F401 (pytest fixture)
from test_knowledge_service import FakeEmbedder  # noqa: F401
from test_platform import database  # noqa: F401 (pytest fixture)


def make_faq_kb(factory, tenant_id, owner, **kwargs):
    kwargs.setdefault('indexing', {'vector': False, 'keyword': True})
    with factory() as db, db.begin():
        return service.create_base(db, tenant_id, owner, visibility='tenant', name=kwargs.pop('name', '常见问题'), kb_type='faq', **kwargs).id


def add(factory, tenant_id, owner, kb_id, question, answers, **extra):
    with factory() as db, db.begin():
        row, notes = faq.create_entry(db, tenant_id, owner, kb_id, {'standard_question': question, 'answers': answers, **extra})
        return row.id, notes


def index(factory):
    while asyncio.run(faq.index_tick(factory)):
        pass


def test_entries_are_searchable_only_after_indexing_and_while_enabled(env):
    factory, tenant_id, _, owner, member, _ = env
    kb_id = make_faq_kb(factory, tenant_id, owner)
    entry_id, _ = add(factory, tenant_id, owner, kb_id, '如何联系客服？', ['拨打客服热线'], similar_questions=['客服电话是多少'])
    assert find(factory, tenant_id, member, '客服电话').hits == []  # pending: not searchable yet
    index(factory)
    hit = find(factory, tenant_id, member, '客服电话').hits[0]
    assert hit.content == '问：如何联系客服？\n答：拨打客服热线' and hit.document_id == str(entry_id)
    # Disabled entries leave search at once, without re-indexing.
    with factory() as db, db.begin():
        faq.batch_fields(db, tenant_id, owner, kb_id, [entry_id], {'is_enabled': False})
    assert find(factory, tenant_id, member, '客服电话').hits == []
    with factory() as db, db.begin():
        faq.batch_fields(db, tenant_id, owner, kb_id, [entry_id], {'is_enabled': True})
    assert find(factory, tenant_id, member, '客服电话').hits
    # An edit takes the entry out of search until it is indexed again, then serves the new answer.
    with factory() as db, db.begin():
        faq.update_entry(db, tenant_id, owner, kb_id, entry_id,
                         {'standard_question': '如何联系客服？', 'answers': ['在线留言'], 'similar_questions': ['客服电话是多少']})
    assert find(factory, tenant_id, member, '客服电话').hits == []
    index(factory)
    assert '在线留言' in find(factory, tenant_id, member, '客服电话').hits[0].content


def test_negative_questions_keep_an_entry_out_of_the_answer(env):
    factory, tenant_id, _, owner, member, _ = env
    kb_id = make_faq_kb(factory, tenant_id, owner)
    add(factory, tenant_id, owner, kb_id, '如何修改密码', ['在设置中修改'], negative_questions=['忘记密码怎么办'])
    add(factory, tenant_id, owner, kb_id, '忘记密码怎么办', ['点击找回密码'])
    index(factory)
    assert [h.document_id and h.filename for h in find(factory, tenant_id, member, '忘记密码怎么办').hits][0] == '忘记密码怎么办'
    assert all(h.filename != '如何修改密码' for h in find(factory, tenant_id, member, '忘记密码怎么办').hits)
    assert any(h.filename == '如何修改密码' for h in find(factory, tenant_id, member, '如何修改密码').hits)


def test_conflicts_import_export_and_deletion(env):
    factory, tenant_id, _, owner, member, _ = env
    kb_id = make_faq_kb(factory, tenant_id, owner)
    add(factory, tenant_id, owner, kb_id, '如何联系客服', ['热线'])
    with factory() as db, db.begin():
        with pytest.raises(Conflict):
            faq.create_entry(db, tenant_id, owner, kb_id, {'standard_question': '如何联系客服!', 'answers': ['x']})
    csv_rows = ('分类,问题,相似问题,反例问题,机器人回答,是否全部回复,是否停用\n'
                '账号,如何联系客服,,,重复,FALSE,FALSE\n'
                '账号,如何改密码,怎么改密码,,在设置修改##或联系客服,TRUE,FALSE\n'
                '账号,,,,缺少问题,FALSE,FALSE\n').encode('utf-8-sig')
    from nexus_knowledge import faq as rules
    with factory() as db, db.begin():
        result = faq.import_entries(db, tenant_id, owner, kb_id, rules.parse_csv(csv_rows), 'append')
    assert result['created'] == 1 and len(result['blocked']) == 2
    assert {b['reason'].split('：')[0] for b in result['blocked']} == {'标准问重复', '标准问不能为空'}
    index(factory)
    with factory() as db:
        exported = faq.export_entries(db, tenant_id, owner, kb_id)
    assert {e['standard_question'] for e in exported} == {'如何联系客服', '如何改密码'}
    # Replace deletes the old entries; deleted entries vanish from search before the worker cleans them up.
    with factory() as db, db.begin():
        faq.import_entries(db, tenant_id, owner, kb_id, [{'standard_question': '新问题', 'answers': ['新答案']}], 'replace')
    assert find(factory, tenant_id, member, '客服').hits == []
    index(factory)
    with factory() as db:
        assert [r.standard_question for r in db.scalars(select(FaqEntryRecord))] == ['新问题']


def test_faq_bases_have_their_own_rules(env):
    factory, tenant_id, _, owner, member, _ = env
    with factory() as db, db.begin():
        with pytest.raises(ValueError, match='graph or wiki'):
            service.create_base(db, tenant_id, owner, visibility='tenant', name='f', kb_type='faq', indexing={'vector': False, 'keyword': True, 'graph': True})
        with pytest.raises(ValueError, match='index_mode'):
            service.create_base(db, tenant_id, owner, visibility='tenant', name='g', kb_type='faq', indexing={'vector': False, 'keyword': True},
                                settings={'faq_config': {'index_mode': 'bogus'}})
    doc_kb = None
    with factory() as db, db.begin():
        doc_kb = service.create_base(db, tenant_id, owner, visibility='tenant', name='文档', indexing={'vector': False, 'keyword': True}).id
    with factory() as db, db.begin():
        with pytest.raises(Conflict):
            faq.create_entry(db, tenant_id, owner, doc_kb, {'standard_question': 'q', 'answers': ['a']})
    kb_id = make_faq_kb(factory, tenant_id, owner)
    from nexus_platform.persistence.models import KnowledgeBaseRecord
    with factory() as db:
        assert service.base_view(db, db.get(KnowledgeBaseRecord, kb_id), tenant_id, owner)['type'] == 'faq'


def test_question_answer_index_mode_matches_on_answers(env, monkeypatch):
    factory, tenant_id, _, owner, member, _ = env
    kb_id = make_faq_kb(factory, tenant_id, owner, name='qa', settings={'faq_config': {
        'index_mode': 'question_answer', 'question_index_mode': 'separate'}})
    add(factory, tenant_id, owner, kb_id, '退款多久到账', ['三个工作日内原路退回'])
    index(factory)
    assert find(factory, tenant_id, member, '原路退回').hits  # the answer text is indexed in this mode


def test_vector_channel_and_failed_embedding(env, monkeypatch):
    factory, tenant_id, _, owner, member, _ = env
    from uuid import uuid4
    monkeypatch.setattr(service, '_authorize_embedding', lambda *a: None)
    failing = []
    embedding.set_embedder_factory(lambda f, t, user, model, purpose: FakeEmbedder(user, purpose, bool(failing)))
    try:
        kb_id = make_faq_kb(factory, tenant_id, owner, name='v', indexing={'vector': True, 'keyword': True},
                            embedding_model_id=uuid4())
        add(factory, tenant_id, owner, kb_id, '苹果多少钱', ['五元'])
        index(factory)
        assert find(factory, tenant_id, member, '苹果').hits[0].ranks.get('vector') == 1
        failing.append(1)
        entry_id, _ = add(factory, tenant_id, owner, kb_id, '香蕉多少钱', ['三元'])
        for _ in range(faq.MAX_ATTEMPTS + 1):
            index(factory)
        with factory() as db:
            row = db.get(FaqEntryRecord, entry_id)
            assert row.index_state == 'failed' and 'RuntimeError' in row.index_error
        failing.clear()
        with factory() as db, db.begin():
            assert faq.retry_failed(db, tenant_id, owner, kb_id) == 1
        index(factory)
        assert find(factory, tenant_id, member, '香蕉').hits
    finally:
        embedding.set_embedder_factory(None)


def test_faq_api(env):
    from cryptography.fernet import Fernet  # noqa: F401
    factory, tenant_id, _, owner, member, _ = env
    kb_id = make_faq_kb(factory, tenant_id, owner)

    def session():
        with factory() as db:
            yield db
    who = [OWNER]
    app.dependency_overrides[get_database_session] = session
    app.dependency_overrides[get_principal] = lambda: who[0]
    try:
        with TestClient(app) as client:
            base = f'/api/v1/tenants/{tenant_id}/knowledge/bases/{kb_id}/faq'
            created = client.post(f'{base}/entries', json={'standard_question': '如何退货', 'answers': ['七天内可退'],
                                                           'similar_questions': ['怎么退货']})
            assert created.status_code == 201, created.text
            assert client.post(f'{base}/entries', json={'standard_question': '如何退货', 'answers': ['x']}).status_code == 409
            upload = client.post(f'{base}/import-file', files={'file': ('faq.csv', '问题,机器人回答\n如何换货,质量问题可换'.encode())},
                                 data={'mode': 'append'})
            assert upload.json()['created'] == 1
            index(factory)
            listing = client.get(f'{base}/entries', params={'keyword': '退货'}).json()
            assert listing['total'] == 1 and listing['items'][0]['index_state'] == 'ready'
            found = client.post(f'{base}/search', json={'query_text': '怎么退货'}).json()
            assert found['items'][0]['content'].startswith('问：如何退货')
            csv_export = client.get(f'{base}/export')
            assert csv_export.status_code == 200 and '如何换货' in csv_export.content.decode('utf-8-sig')
            ids = [item['id'] for item in client.get(f'{base}/entries').json()['items']]
            assert client.patch(f'{base}/entries', json={'ids': ids, 'is_enabled': False}).json()['updated'] == 2
            assert client.post(f'{base}/entries/delete', json={'ids': ids}).json()['deleted'] == 2
            who[0] = Principal_member(member)
            assert client.post(f'{base}/entries', json={'standard_question': 'q', 'answers': ['a']}).status_code == 403
    finally:
        app.dependency_overrides.clear()


def Principal_member(_):
    from nexus_core.platform import Principal
    return Principal('kb-member', 'test')
