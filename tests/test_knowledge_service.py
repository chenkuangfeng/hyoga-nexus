"""Knowledge service, jobs and Pre-Filter search on SQLite (openspec 2026-11-06-knowledge-base K1.4–K1.7)."""
import asyncio
import hashlib
from uuid import uuid4

import pytest
from sqlalchemy import select

from nexus_core.platform import Principal, utc_now
from nexus_knowledge import capabilities
from nexus_platform.authz.resources import grant_resource, revoke_resource_grant
from nexus_platform.errors import Conflict, Forbidden, NotFound
from nexus_platform.identity.service import resolve_user
from nexus_platform.knowledge import embedding, jobs, search, service
from nexus_platform.persistence.models import (AuditRecord, KnowledgeChunkRecord, KnowledgeDocumentRecord,
                                               KnowledgeDocumentVersionRecord, KnowledgeJobRecord, MembershipRecord)
from nexus_platform.tenants.service import create_tenant

from test_platform import database  # noqa: F401 (pytest fixture)

OWNER = Principal('kb-owner', 'test')
MEMBER = Principal('kb-member', 'test')
OUTSIDER = Principal('kb-outsider', 'test')


@pytest.fixture
def env(database, deployment_config, tmp_path):
    deployment_config(f'[knowledge]\ndata_dir = "{tmp_path / "kdata"}"\n')
    with database() as db:
        tenant = create_tenant(db, OWNER, 'Space A')
        other = create_tenant(db, OUTSIDER, 'Space B')
        with db.begin():
            owner = resolve_user(db, OWNER)
            member = resolve_user(db, MEMBER)
            outsider = resolve_user(db, OUTSIDER)
            db.add(MembershipRecord(tenant_id=tenant.id, user_id=member.id, role='contributor', status='active',
                                    joined_at=utc_now()))
    return database, tenant.id, other.id, owner.id, member.id, outsider.id


def run(coro):
    return asyncio.run(coro)


def create_kb(factory, tenant_id, user_id, name='手册', **kwargs):
    kwargs.setdefault('indexing', {'vector': False, 'keyword': True})
    with factory() as db, db.begin():
        return service.create_base(db, tenant_id, user_id, name=name, **kwargs).id


def upload(factory, tenant_id, user_id, kb_id, filename, data):
    with factory() as db:
        kb, digest, duplicate = service.prepare_upload(db, tenant_id, user_id, kb_id, filename, data, 10 << 20)
        if duplicate is not None:
            return duplicate.id, True
        from nexus_platform.knowledge import stores
        doc_id, version_id = uuid4(), uuid4()
        existing = db.scalar(select(KnowledgeDocumentRecord).where(KnowledgeDocumentRecord.kb_id == kb.id,
                                                                   KnowledgeDocumentRecord.filename == filename,
                                                                   KnowledgeDocumentRecord.status == 'active'))
        key_doc = existing.id if existing else doc_id
        run(stores.blob_store_for(db, kb).put(service.blob_key(kb, key_doc, version_id), data))
    with factory() as db, db.begin():
        kb = db.get(type(kb), kb_id)
        doc, _ = service.add_version(db, kb, user_id, filename, digest, len(data), key_doc, version_id)
        return doc.id, False


def drain(factory):
    while run(jobs.run_due(factory, 5)):
        pass


def find(factory, tenant_id, user_id, query, **kwargs):
    with factory() as db:
        result = run(search.search(factory, db, tenant_id, user_id, query, **kwargs))
        db.commit()
    return result


def test_upload_index_and_keyword_search(env):
    factory, tenant_id, _, owner, member, _ = env
    kb_id = create_kb(factory, tenant_id, owner)
    doc_id, dup = upload(factory, tenant_id, owner, kb_id, '退货政策.md',
                         '# 退货\n商品签收七天内可以无理由退货。\n# 换货\n质量问题可以换货。'.encode())
    assert not dup
    drain(factory)
    with factory() as db:
        doc = db.get(KnowledgeDocumentRecord, doc_id)
        version = db.get(KnowledgeDocumentVersionRecord, doc.current_version_id)
        assert version.state == 'ready' and version.chunk_count == 2 and version.indexed_count == 2
    result = find(factory, tenant_id, member, '无理由退货')
    assert result.hits and result.hits[0].filename == '退货政策.md'
    assert result.hits[0].section == ['退货'] and result.hits[0].ranks.get('keyword') == 1
    assert result.degraded == []
    # Same bytes again: deduplicated, no new version or job.
    assert upload(factory, tenant_id, owner, kb_id, '别名.md',
                  '# 退货\n商品签收七天内可以无理由退货。\n# 换货\n质量问题可以换货。'.encode()) == (doc_id, True)


def test_new_version_becomes_visible_only_when_ready(env):
    factory, tenant_id, _, owner, member, _ = env
    kb_id = create_kb(factory, tenant_id, owner)
    doc_id, _ = upload(factory, tenant_id, owner, kb_id, 'faq.txt', '旧版本内容：苹果'.encode())
    drain(factory)
    upload(factory, tenant_id, owner, kb_id, 'faq.txt', '新版本内容：香蕉'.encode())
    assert [h.content for h in find(factory, tenant_id, member, '苹果').hits] == ['旧版本内容：苹果']
    assert find(factory, tenant_id, member, '香蕉').hits == []  # not indexed yet
    drain(factory)
    assert find(factory, tenant_id, member, '苹果').hits == []
    assert [h.content for h in find(factory, tenant_id, member, '香蕉').hits] == ['新版本内容：香蕉']
    with factory() as db:
        versions = service.list_versions(db, tenant_id, member, doc_id)
        assert [(v.version, v.state) for v in versions] == [(2, 'ready'), (1, 'superseded')]


def test_scope_excludes_unreadable_shared_revoked_and_deleted(env):
    factory, tenant_id, other_id, owner, member, outsider = env
    kb_a = create_kb(factory, tenant_id, owner, 'A')
    kb_b = create_kb(factory, other_id, outsider, 'B')
    upload(factory, tenant_id, owner, kb_a, 'a.txt', '共同关键词 甲'.encode())
    upload(factory, other_id, outsider, kb_b, 'b.txt', '共同关键词 乙'.encode())
    drain(factory)
    assert {h.kb_id for h in find(factory, tenant_id, member, '共同关键词').hits} == {str(kb_a)}
    # Requesting a base of another space is ignored, never searched.
    result = find(factory, tenant_id, member, '共同关键词', requested=[kb_b])
    assert result.hits == [] and result.ignored == [str(kb_b)]
    # Shared into space A: readable from A; revoked: gone at the next search.
    with factory() as db:
        grant = grant_resource(db, OUTSIDER, source_tenant_id=other_id, target_tenant_id=tenant_id,
                               kind='knowledge_base', resource_id=str(kb_b), permissions=['read'])
    assert {h.kb_id for h in find(factory, tenant_id, member, '共同关键词').hits} == {str(kb_a), str(kb_b)}
    with factory() as db:
        revoke_resource_grant(db, OUTSIDER, grant.id)
    assert {h.kb_id for h in find(factory, tenant_id, member, '共同关键词').hits} == {str(kb_a)}
    # An agent bound to nothing searches nothing; bound bases limit the scope.
    assert find(factory, tenant_id, member, '共同关键词', bound=[]).hits == []
    assert find(factory, tenant_id, member, '共同关键词', bound=[kb_b]).hits == []
    # Deleting the base hides it immediately, before cleanup runs.
    with factory() as db, db.begin():
        service.delete_base(db, tenant_id, owner, kb_a)
    assert find(factory, tenant_id, member, '共同关键词').hits == []
    drain(factory)
    with factory() as db:
        assert db.scalar(select(KnowledgeChunkRecord).where(KnowledgeChunkRecord.kb_id == kb_a)) is None


def test_deleted_document_disappears_and_is_cleaned_up(env):
    factory, tenant_id, _, owner, member, _ = env
    kb_id = create_kb(factory, tenant_id, owner)
    doc_id, _ = upload(factory, tenant_id, owner, kb_id, 'x.md', '# 标题\n可删除的内容'.encode())
    drain(factory)
    with factory() as db, db.begin():
        service.delete_document(db, tenant_id, owner, doc_id)
    assert find(factory, tenant_id, member, '可删除').hits == []
    drain(factory)
    with factory() as db:
        assert db.get(KnowledgeDocumentRecord, doc_id) is None
        assert db.scalar(select(KnowledgeDocumentVersionRecord)) is None


def test_write_access_and_capability_checks(env):
    factory, tenant_id, other_id, owner, member, outsider = env
    kb_id = create_kb(factory, tenant_id, owner)
    with factory() as db:
        with pytest.raises(Forbidden):
            service.prepare_upload(db, tenant_id, member, kb_id, 'a.txt', b'x', 100)
        with pytest.raises(NotFound):
            service.prepare_upload(db, other_id, outsider, kb_id, 'a.txt', b'x', 100)
        with pytest.raises(ValueError):
            service.prepare_upload(db, tenant_id, owner, kb_id, 'a.doc', b'x', 100)
        with pytest.raises(ValueError):
            service.prepare_upload(db, tenant_id, owner, kb_id, 'a.txt', b'x' * 200, 100)
    with factory() as db, db.begin():
        with pytest.raises(capabilities.CapabilityPlanned):
            service.create_base(db, tenant_id, owner, name='wiki', kb_type='wiki', indexing={'vector': False, 'keyword': True})
        with pytest.raises(capabilities.CapabilityPlanned):
            service.create_base(db, tenant_id, owner, name='w', indexing={'keyword': True, 'wiki': True})
        with pytest.raises(ValueError, match='chat model'):  # graph is implemented but needs its configuration
            service.create_base(db, tenant_id, owner, name='g', indexing={'keyword': True, 'graph': True})
        with pytest.raises(ValueError):
            service.create_base(db, tenant_id, owner, name='v', indexing={'vector': True, 'keyword': True})
        with pytest.raises(Conflict):
            service.create_base(db, tenant_id, owner, name='手册', indexing={'vector': False, 'keyword': True})
    # A contributor may create their own base and then change it.
    mine = create_kb(factory, tenant_id, member, '我的库')
    with factory() as db, db.begin():
        service.update_base(db, tenant_id, member, mine, {'description': '说明'})


def test_unparseable_document_fails_with_reason_and_can_retry(env):
    factory, tenant_id, _, owner, _, _ = env
    kb_id = create_kb(factory, tenant_id, owner)
    doc_id, _ = upload(factory, tenant_id, owner, kb_id, 'empty.md', '   \n'.encode())
    drain(factory)
    with factory() as db:
        doc = db.get(KnowledgeDocumentRecord, doc_id)
        version = db.get(KnowledgeDocumentVersionRecord, doc.latest_version_id)
        assert (version.state, version.error_code) == ('failed', 'empty_text')
        assert db.scalar(select(KnowledgeJobRecord.state).where(KnowledgeJobRecord.version_id == version.id)) == 'failed'
    with factory() as db, db.begin():
        assert service.retry_document(db, tenant_id, owner, doc_id).state == 'pending'


class FakeEmbedder:
    calls = []

    def __init__(self, user_id, purpose, fail=False):
        self.user_id, self.purpose, self.fail = user_id, purpose, fail

    async def embed(self, texts):
        FakeEmbedder.calls.append((self.purpose, len(texts)))
        if self.fail:
            raise RuntimeError('provider down')
        return [[1.0, 0.0] if '苹果' in text else [0.0, 1.0] for text in texts]

    async def close(self):
        pass


def test_hybrid_search_and_vector_degradation(env, monkeypatch):
    factory, tenant_id, _, owner, member, _ = env
    monkeypatch.setattr(service, '_authorize_embedding', lambda *args: None)
    failing = set()
    embedding.set_embedder_factory(lambda f, t, user, model, purpose: FakeEmbedder(user, purpose, user in failing))
    try:
        kb_id = create_kb(factory, tenant_id, owner, indexing={'vector': True, 'keyword': True},
                          embedding_model_id=uuid4())
        upload(factory, tenant_id, owner, kb_id, 'fruit.txt', '苹果很好吃'.encode())
        upload(factory, tenant_id, owner, kb_id, 'other.txt', '天气晴朗'.encode())
        drain(factory)
        assert ('knowledge.embedding', 1) in FakeEmbedder.calls
        result = find(factory, tenant_id, member, '苹果')
        assert result.hits[0].filename == 'fruit.txt'
        assert result.hits[0].ranks == {'vector': 1, 'keyword': 1} and result.degraded == []
        failing.add(member)
        result = find(factory, tenant_id, member, '苹果')
        assert result.hits[0].filename == 'fruit.txt'
        assert result.degraded == [{'kb_id': str(kb_id), 'channel': 'vector', 'reason': 'embedding_failed'}]
        with factory() as db:
            assert db.scalar(select(AuditRecord).where(AuditRecord.action == 'knowledge.search_degraded')) is not None
    finally:
        embedding.set_embedder_factory(None)


def test_parent_child_chunking_matches_children_and_returns_parents(env):
    factory, tenant_id, _, owner, member, _ = env
    settings = {'chunking_config': {'enable_parent_child': True, 'parent_chunk_size': 600, 'child_chunk_size': 150,
                                    'strategy': 'recursive'}}
    kb_id = create_kb(factory, tenant_id, owner, name='父子', settings=settings)
    text = ''.join(f'第{i}段讲的是产品功能说明。' for i in range(60)) + '独一无二的关键短语位于末尾。'
    doc_id, _ = upload(factory, tenant_id, owner, kb_id, '手册.txt', text.encode())
    drain(factory)
    from nexus_platform.persistence.models import KnowledgeChunkRecord
    with factory() as db:
        doc = db.get(KnowledgeDocumentRecord, doc_id)
        rows = db.scalars(select(KnowledgeChunkRecord).where(KnowledgeChunkRecord.version_id == doc.current_version_id)).all()
        parents = [r for r in rows if r.parent_id is None]
        children = [r for r in rows if r.parent_id is not None]
        assert parents and children and all(not r.indexed for r in parents) and all(r.indexed for r in children)
        version = db.get(KnowledgeDocumentVersionRecord, doc.current_version_id)
        assert version.chunk_count == len(parents) and version.indexed_count == len(children)
        listed, total = service.chunks_of(db, tenant_id, member, doc_id)
        assert total == len(parents)  # readers see parents, not the small children
    result = find(factory, tenant_id, member, '独一无二的关键短语')
    assert len(result.hits) == 1
    hit = result.hits[0]
    assert '独一无二的关键短语' in hit.content and 150 < len(hit.content) <= 600  # the parent, not the child


def test_docx_upload_is_indexed_with_heading_sections(env):
    import io
    import zipfile
    factory, tenant_id, _, owner, member, _ = env
    w = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    document = (f'<w:document {w}><w:body>'
                '<w:p><w:pPr><w:pStyle w:val="H1"/></w:pPr><w:r><w:t>报销制度</w:t></w:r></w:p>'
                '<w:p><w:r><w:t>差旅费需在出差结束后五个工作日内提交报销。</w:t></w:r></w:p>'
                '<w:p><w:pPr><w:pStyle w:val="H1"/></w:pPr><w:r><w:t>请假制度</w:t></w:r></w:p>'
                '<w:p><w:r><w:t>年假需提前三天申请。</w:t></w:r></w:p></w:body></w:document>')
    styles = f'<w:styles {w}><w:style w:styleId="H1"><w:name w:val="heading 1"/></w:style></w:styles>'
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        archive.writestr('word/document.xml', document)
        archive.writestr('word/styles.xml', styles)
    kb_id = create_kb(factory, tenant_id, owner, name='制度')
    upload(factory, tenant_id, owner, kb_id, '制度.docx', buffer.getvalue())
    drain(factory)
    hit = find(factory, tenant_id, member, '年假').hits[0]
    assert hit.section == ['请假制度'] and hit.filename == '制度.docx'
