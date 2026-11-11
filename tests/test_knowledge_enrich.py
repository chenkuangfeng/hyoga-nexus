"""LLM enrichment: summaries, generated questions, auto tags, profile (openspec 2026-11-06-knowledge-base K5.2)."""
import asyncio
import json
from uuid import uuid4

import pytest
from sqlalchemy import select

from nexus_platform.knowledge import enrich, service
from nexus_platform.knowledge.graph import llm
from nexus_platform.persistence.models import (KnowledgeBaseRecord, KnowledgeChunkRecord, KnowledgeDocumentRecord,
                                               KnowledgeDocumentVersionRecord, KnowledgeJobRecord, KnowledgeTagRecord)

from test_knowledge_service import drain, env, find, upload  # noqa: F401 (pytest fixture)
from test_platform import database  # noqa: F401 (pytest fixture)


class Scripted:
    def __init__(self):
        self.calls = []
        self.fail = False

    async def __call__(self, factory, tenant, user, model, purpose, system, text, max_tokens):
        if self.fail:
            raise RuntimeError('provider down')
        if '文档摘要' in system:
            kind, reply = 'summary', {'summary': '介绍退货政策与退款时限。'}
        elif '检索辅助' in system:
            kind, reply = 'questions', {'items': [{'n': 0, 'questions': ['东西买错了怎么处理？', '多久可以拿回钱？']}]}
        elif '文档分类' in system:
            kind, reply = 'tags', {'tags': ['售后', '制度']}
        elif '知识库说明' in system:
            kind, reply = 'profile', {'description': '收录售后与退换货制度，适合回答退货退款问题。'}
        else:
            kind, reply = 'other', {}
        self.calls.append(kind)
        return json.dumps(reply, ensure_ascii=False)


@pytest.fixture
def enriched(env, monkeypatch):
    factory, tenant_id, _, owner, member, _ = env
    monkeypatch.setattr(service, '_authorize_chat_model', lambda *args: None)
    model = Scripted()
    llm.set_completer(model)
    settings = {'summary_model_id': str(uuid4()),
                'question_generation_config': {'enabled': True, 'question_count': 2},
                'auto_tag_config': {'enabled': True, 'max_tags': 2},
                'profile_config': {'enabled': True}}
    with factory() as db, db.begin():
        kb_id = service.create_base(db, tenant_id, owner, visibility='tenant', name='售后', settings=settings,
                                    indexing={'vector': False, 'keyword': True}).id
    yield factory, tenant_id, owner, member, kb_id, model
    llm.set_completer(None)


def test_enrichment_adds_summary_questions_tags_and_profile(enriched):
    factory, tenant_id, owner, member, kb_id, model = enriched
    doc_id, _ = upload(factory, tenant_id, owner, kb_id, '退货.md', '# 退货\n商品签收七天内可以申请退货，退款三个工作日到账。'.encode())
    drain(factory)
    assert model.calls.count('summary') == 1 and model.calls.count('questions') == 1 and model.calls.count('tags') == 1
    assert 'profile' in model.calls
    with factory() as db:
        doc = db.get(KnowledgeDocumentRecord, doc_id)
        version = db.get(KnowledgeDocumentVersionRecord, doc.current_version_id)
        assert version.summary == '介绍退货政策与退款时限。'
        assert version.enrichment == {'summary': 'done', 'questions': 'done', 'tags': 'done'}
        chunk = db.scalar(select(KnowledgeChunkRecord).where(KnowledgeChunkRecord.version_id == version.id))
        assert chunk.questions == ['东西买错了怎么处理？', '多久可以拿回钱？']
        assert sorted(t.name for t in db.scalars(select(KnowledgeTagRecord))) == ['制度', '售后']
        assert sorted(doc.tag_ids) == sorted(str(t.id) for t in db.scalars(select(KnowledgeTagRecord)))
        kb = db.get(KnowledgeBaseRecord, kb_id)
        assert kb.settings['generated_profile']['description'].startswith('收录售后')
        assert service.document_view(db, doc)['summary'] == '介绍退货政策与退款时限。'
    # The user's wording is not in the document; the generated question finds the chunk.
    hits = find(factory, tenant_id, member, '东西买错了怎么处理').hits
    assert hits and hits[0].filename == '退货.md' and hits[0].ranks.get('keyword') == 1
    # Replacing the document enriches the new version again (and only it).
    upload(factory, tenant_id, owner, kb_id, '退货.md', '# 退货\n新版本内容，换货十五天内免费。'.encode())
    drain(factory)
    assert model.calls.count('summary') == 2


def test_failing_model_retries_without_failing_the_version(enriched):
    factory, tenant_id, owner, member, kb_id, model = enriched
    model.fail = True
    doc_id, _ = upload(factory, tenant_id, owner, kb_id, '退货.md', '# 退货\n七天内可以申请退货。'.encode())
    asyncio.run(__import__('nexus_platform.knowledge.jobs', fromlist=['x']).run_due(factory, 5))  # index job
    asyncio.run(__import__('nexus_platform.knowledge.jobs', fromlist=['x']).run_due(factory, 5))  # enrich job fails once
    with factory() as db:
        doc = db.get(KnowledgeDocumentRecord, doc_id)
        version = db.get(KnowledgeDocumentVersionRecord, doc.current_version_id)
        assert version.state == 'ready' and not version.enrichment  # searchable and unharmed
        job = db.scalar(select(KnowledgeJobRecord).where(KnowledgeJobRecord.kind == 'enrich'))
        assert job.state == 'pending' and job.attempts == 1 and 'RuntimeError' in job.last_error
    assert find(factory, tenant_id, member, '七天内').hits
    model.fail = False
    with factory() as db, db.begin():
        for job in db.scalars(select(KnowledgeJobRecord).where(KnowledgeJobRecord.kind == 'enrich')):
            from nexus_core.platform import utc_now
            job.available_at = utc_now()
    drain(factory)
    with factory() as db:
        assert db.get(KnowledgeDocumentVersionRecord, version.id).enrichment.get('summary') == 'done'


def test_enrichment_settings_are_validated(env, monkeypatch):
    factory, tenant_id, _, owner, member, _ = env
    monkeypatch.setattr(service, '_authorize_chat_model', lambda *args: None)
    with factory() as db, db.begin():
        with pytest.raises(ValueError, match='question_count'):
            service.create_base(db, tenant_id, owner, visibility='tenant', name='a', indexing={'vector': False, 'keyword': True},
                                settings={'question_generation_config': {'enabled': True, 'question_count': 50}})
        with pytest.raises(ValueError, match='max_tags'):
            service.create_base(db, tenant_id, owner, visibility='tenant', name='b', indexing={'vector': False, 'keyword': True},
                                settings={'auto_tag_config': {'enabled': True, 'max_tags': 0}})
        kb = service.create_base(db, tenant_id, owner, visibility='tenant', name='c', indexing={'vector': False, 'keyword': True})
        with pytest.raises(ValueError, match='profile'):
            enrich.request_profile(db, kb)
