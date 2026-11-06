"""Graph builds, search and tools on SQLite with a scripted chat model (openspec 2026-11-06-knowledge-base K2)."""
import asyncio
import json
from uuid import uuid4

import pytest
from sqlalchemy import select

from nexus_core.platform import utc_now
from nexus_platform.knowledge import service
from nexus_platform.knowledge.graph import build, llm, search as graph_search
from nexus_platform.persistence.models import (GraphBuildRecord, GraphEntityRecord, GraphExtractionCacheRecord,
                                               KnowledgeDocumentRecord)

from test_knowledge_service import OWNER, drain, env, find, upload  # noqa: F401 (pytest fixture)
import test_knowledge_tools as kt
from test_knowledge_tools import _agent, _run
from test_platform import database  # noqa: F401 (pytest fixture)

TEXTS = {
    '公司.md': '# 公司\n甲公司由张三创立，总部位于上海。甲公司生产乙产品。',
    '产品.md': '# 产品\n乙产品面向企业客户销售，由丙团队维护。丙团队隶属于甲公司。',
}


class ScriptedModel:
    """Answers extraction by keyword, and community reports; counts calls."""

    def __init__(self):
        self.calls = []

    async def __call__(self, factory, tenant, user, model, purpose, system, text, max_tokens):
        self.calls.append(('report' if '社区' in system else 'extract', text))
        if '社区' in system:
            return json.dumps({'title': '甲公司及产品', 'summary': '甲公司生产乙产品，由丙团队维护。'}, ensure_ascii=False)
        entities, relations = [], []
        if '甲公司' in text:
            entities += [{'name': '甲公司', 'type': '组织', 'description': '一家公司'},
                         {'name': '张三', 'type': '人物', 'description': '创始人'}]
            relations.append({'source': '张三', 'target': '甲公司', 'description': '创立', 'weight': 6})
        if '乙产品' in text:
            entities.append({'name': '乙产品', 'type': '产品', 'description': '面向企业的产品'})
            relations.append({'source': '甲公司', 'target': '乙产品', 'description': '生产', 'weight': 5})
        if '丙团队' in text:
            entities.append({'name': '丙团队', 'type': '组织', 'description': '维护团队'})
            relations.append({'source': '丙团队', 'target': '乙产品', 'description': '维护', 'weight': 4})
        return json.dumps({'entities': entities, 'relations': relations}, ensure_ascii=False)


@pytest.fixture
def graph_env(env, monkeypatch):
    factory, tenant_id, _, owner, member, _ = env
    monkeypatch.setattr(service, '_authorize_chat_model', lambda *args: None)
    model = ScriptedModel()
    llm.set_completer(model)
    yield factory, tenant_id, owner, member, model
    llm.set_completer(None)


def make_graph_kb(factory, tenant_id, owner, mode='graphrag_light'):
    settings = {'graph': {'mode': mode, 'model_id': str(uuid4()), 'entity_types': ['组织', '人物', '产品']}}
    with factory() as db, db.begin():
        return service.create_base(db, tenant_id, owner, name=f'图谱-{mode}', settings=settings,
                                   indexing={'vector': False, 'keyword': True, 'graph': True}).id


def run_builds(factory, delay_past=True):
    if delay_past:
        with factory() as db, db.begin():
            for b in db.scalars(select(GraphBuildRecord).where(GraphBuildRecord.state == 'pending')):
                b.available_at = utc_now()
    return asyncio.run(build.run_due(factory, 5))


def test_build_extracts_merges_and_caches(graph_env):
    factory, tenant_id, owner, member, model = graph_env
    kb_id = make_graph_kb(factory, tenant_id, owner)
    for name, text in TEXTS.items():
        upload(factory, tenant_id, owner, kb_id, name, text.encode())
    drain(factory)
    with factory() as db:
        assert db.scalars(select(GraphBuildRecord).where(GraphBuildRecord.state == 'pending')).all()  # debounced build
    assert run_builds(factory) >= 1
    with factory() as db:
        ready = db.scalar(select(GraphBuildRecord).where(GraphBuildRecord.state == 'ready'))
        assert (ready.entity_count, ready.relation_count) == (4, 3)  # 甲公司 merged across both documents
        assert ready.progress['model_calls'] == 2
        names = sorted(e.name for e in db.scalars(select(GraphEntityRecord)))
        assert names == ['丙团队', '乙产品', '张三', '甲公司']
    calls_before = len(model.calls)
    # A rebuild without document changes reuses the cache: no model call.
    with factory() as db, db.begin():
        service.rebuild_base(db, tenant_id, owner, kb_id)
    run_builds(factory)  # documents are being re-indexed: the build waits
    with factory() as db:
        assert db.scalar(select(GraphBuildRecord).where(GraphBuildRecord.state == 'ready')) is not None
        assert db.scalar(select(GraphBuildRecord).where(GraphBuildRecord.state == 'pending')) is not None
    drain(factory)
    run_builds(factory)
    assert len(model.calls) == calls_before
    with factory() as db:
        assert db.scalar(select(GraphBuildRecord).where(GraphBuildRecord.state == 'superseded')) is not None
        assert len(db.scalars(select(GraphEntityRecord)).all()) == 4  # the old build's rows were deleted


def test_general_mode_builds_community_reports(graph_env, monkeypatch):
    from nexus_knowledge.graph import community as community_rules
    monkeypatch.setattr(community_rules, 'MIN_SIZE', 2)  # the fixture graph has only four entities
    factory, tenant_id, owner, member, model = graph_env
    kb_id = make_graph_kb(factory, tenant_id, owner, 'graphrag_general')
    for name, text in TEXTS.items():
        upload(factory, tenant_id, owner, kb_id, name, text.encode())
    drain(factory)
    run_builds(factory)
    with factory() as db:
        ready = db.scalar(select(GraphBuildRecord).where(GraphBuildRecord.state == 'ready'))
        assert ready.community_count >= 1
    assert any(kind == 'report' for kind, _ in model.calls)


def test_agent_tools_return_graph_context_with_citable_handles(graph_env, monkeypatch):
    monkeypatch.setattr(kt, 'OWNER', OWNER)
    factory, tenant_id, owner, member, model = graph_env
    kb_id = make_graph_kb(factory, tenant_id, owner)
    for name, text in TEXTS.items():
        upload(factory, tenant_id, owner, kb_id, name, text.encode())
    drain(factory)
    run_builds(factory)
    from nexus_platform.tenants.service import create_tenant  # noqa: F401
    from nexus_platform.persistence.models import TenantRecord
    with factory() as db:
        tenant = db.get(TenantRecord, tenant_id)
    version = _agent(factory, tenant, [kb_id], tools=['search_knowledge', 'read_document', 'list_documents',
                                                       'query_knowledge_graph'])
    _, context, store = _run(factory, tenant, version)
    found = asyncio.run(store.search_knowledge('甲公司生产什么', [], 5, context.progress.state))
    assert '<knowledge_graph>' in found and '甲公司' in found and '乙产品' in found and '[ID:' in found
    answer = asyncio.run(store.query_knowledge_graph(['丙团队'], None, 2, context.progress.state))
    assert '丙团队' in answer and '维护' in answer and '[ID:' in answer
    assert 'No matching entities' in asyncio.run(store.query_knowledge_graph(['不存在的名字'], None, 2, context.progress.state))


def test_replaced_document_content_is_not_returned_before_the_rebuild(graph_env):
    factory, tenant_id, owner, member, model = graph_env
    kb_id = make_graph_kb(factory, tenant_id, owner)
    doc_id, _ = upload(factory, tenant_id, owner, kb_id, '公司.md', TEXTS['公司.md'].encode())
    drain(factory)
    run_builds(factory)

    def lookup(names):
        async def go():
            with factory() as db:
                from nexus_platform.knowledge import search as base_search
                scoped, _ = base_search.resolve_scope(db, tenant_id, member)
                item = scoped[0]
                build_row = graph_search.ready_build(db, item.kb.id)
                from nexus_knowledge.graph.retrieve import Limits
                return await graph_search.lookup_entities(factory, db, item.kb, build_row, set(item.version_ids), names, Limits())
        return asyncio.run(go())

    assert {e.name for e in lookup(['甲公司']).entities} >= {'甲公司', '张三'}
    # The document is replaced; the old graph elements must disappear at once, before any rebuild ran.
    upload(factory, tenant_id, owner, kb_id, '公司.md', '全新的内容，只有丁机构。'.encode())
    drain(factory)
    assert lookup(['甲公司']).empty()
    # Deleting the document also hides everything.
    with factory() as db, db.begin():
        service.delete_document(db, tenant_id, owner, doc_id)
    assert lookup(['甲公司']).empty()


def test_failed_model_marks_the_build_failed_without_touching_the_visible_graph(graph_env):
    factory, tenant_id, owner, member, model = graph_env
    kb_id = make_graph_kb(factory, tenant_id, owner)
    upload(factory, tenant_id, owner, kb_id, '公司.md', TEXTS['公司.md'].encode())
    drain(factory)
    run_builds(factory)

    async def broken(*args):
        raise RuntimeError('provider down')
    llm.set_completer(broken)
    upload(factory, tenant_id, owner, kb_id, '产品.md', TEXTS['产品.md'].encode())
    drain(factory)
    for _ in range(build.MAX_ATTEMPTS + 1):
        with factory() as db, db.begin():
            for b in db.scalars(select(GraphBuildRecord).where(GraphBuildRecord.state == 'pending')):
                b.available_at = utc_now()
        asyncio.run(build.run_due(factory, 5))
    with factory() as db:
        failed = db.scalar(select(GraphBuildRecord).where(GraphBuildRecord.state == 'failed'))
        assert failed is not None and 'RuntimeError' in failed.error
        assert db.scalar(select(GraphBuildRecord).where(GraphBuildRecord.state == 'ready')) is not None


def test_graph_api_status_rebuild_and_browse(graph_env):
    from cryptography.fernet import Fernet  # noqa: F401
    from fastapi.testclient import TestClient
    from nexus_api.dependencies.platform import get_database_session, get_principal
    from nexus_api.main import app

    factory, tenant_id, owner, member, model = graph_env
    kb_id = make_graph_kb(factory, tenant_id, owner)
    for name, text in TEXTS.items():
        upload(factory, tenant_id, owner, kb_id, name, text.encode())
    drain(factory)
    run_builds(factory)

    def session():
        with factory() as db:
            yield db
    who = [OWNER]
    app.dependency_overrides[get_database_session] = session
    app.dependency_overrides[get_principal] = lambda: who[0]
    try:
        with TestClient(app) as client:
            path = f'/api/v1/tenants/{tenant_id}/knowledge'
            status = client.get(f'{path}/bases/{kb_id}/graph').json()
            assert status['enabled'] and status['ready']['entity_count'] == 4
            assert status['config']['mode'] == 'graphrag_light'
            stores = {s['engine']: s for s in client.get(f'{path}/graph-stores').json()['items']}
            assert stores['builtin']['status'] == 'available' and stores['neo4j']['status'] == 'planned'
            top = client.get(f'{path}/bases/{kb_id}/graph/overview').json()
            assert {n['name'] for n in top['nodes']} == {'甲公司', '张三', '乙产品', '丙团队'} and top['edges']
            named = client.get(f'{path}/bases/{kb_id}/graph/overview', params={'names': '张三', 'hops': 1}).json()
            assert {n['name'] for n in named['nodes']} == {'张三', '甲公司'}
            assert client.post(f'{path}/bases/{kb_id}/graph/rebuild').status_code == 202
    finally:
        app.dependency_overrides.clear()
