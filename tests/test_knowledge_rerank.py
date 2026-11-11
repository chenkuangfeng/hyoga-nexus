"""Rerank policy, protocol clients and search integration (openspec 2026-11-06-knowledge-base K5.3b).

The protocol clients are exercised against a mock transport only; real providers are pending.
"""
import asyncio
import json

import httpx
import pytest

from nexus_knowledge.retrieval import rerank as policy
from nexus_platform.knowledge import rerank as platform_rerank
from nexus_platform.knowledge import service
from nexus_runtimes.native.models.rerank import HttpReranker, RerankError

from test_knowledge_service import create_kb, drain, env, find, upload  # noqa: F401 (pytest fixture)
from test_platform import database  # noqa: F401 (pytest fixture)


def test_threshold_degrades_then_falls_back_to_the_best_passage():
    scores = [(0, 0.9), (1, 0.4), (2, 0.1)]
    assert policy.apply_threshold(scores, 0.5) == ([(0, 0.9)], 'ok', 0.5)
    low = [(0, 0.35), (1, 0.31), (2, 0.1)]
    passing, outcome, effective = policy.apply_threshold(low, 0.5)
    assert outcome == 'threshold_degraded' and effective == pytest.approx(0.35) and [i for i, _ in passing] == [0]
    assert policy.apply_threshold([(0, 0.2), (1, 0.1)], 0.3) == ([(0, 0.2)], 'fallback_top1', 0.3)
    assert policy.apply_threshold([(0, 0.05)], 0.2) == ([], 'all_below_threshold', 0.2)


def test_blend_and_mmr_prefer_diverse_high_scores():
    assert policy.blend(1.0, 1.0) == pytest.approx(1.0) and policy.blend(0.5, 0.5) == pytest.approx(0.55)
    texts = ['退货流程 七天 退款', '退货流程 七天 退款 到账', '安装步骤 双击 运行']
    assert policy.select_mmr(texts, [0.9, 0.88, 0.6], 2) == [0, 2]  # the near-duplicate is skipped
    assert policy.select_mmr(texts, [0.9, 0.88, 0.6], 0) == []


def test_rerank_fills_diagnostics_and_orders_by_blended_score():
    diag = policy.Diagnostics()
    result = policy.rerank([(0, 0.2), (1, 0.95), (7, 0.9)], [0.9, 0.5], ['a', 'b'], threshold=0.1, top_k=2, diag=diag)
    assert [r.index for r in result] == [1, 0] and diag.outcome == 'ok' and diag.result_count == 2
    assert diag.top_score == 0.95  # an out-of-range index is ignored


def _client(api, handler, monkeypatch=None):
    import nexus_runtimes.native.models.rerank as module
    original = module.provider_client
    module.provider_client = lambda *a, **k: httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        return HttpReranker(model='m', api_key='k', base_url='http://rerank.test/v1', api=api)
    finally:
        module.provider_client = original


def test_three_wire_shapes():
    seen = {}

    def cohere(request):
        seen['cohere'] = (request.url.path, json.loads(request.content))
        return httpx.Response(200, json={'results': [{'index': 1, 'relevance_score': 0.9}, {'index': 0, 'relevance_score': 0.1}]})

    def tei(request):
        seen['tei'] = (request.url.path, json.loads(request.content))
        return httpx.Response(200, json=[{'index': 0, 'score': 0.7}])

    def dash(request):
        seen['dash'] = (request.url.path, json.loads(request.content))
        return httpx.Response(200, json={'output': {'results': [{'index': 0, 'relevance_score': 0.6}]}})

    assert asyncio.run(_client('cohere', cohere).rerank('q', ['a', 'b'])) == [(1, 0.9), (0, 0.1)]
    assert seen['cohere'][0] == '/v1/rerank' and seen['cohere'][1]['documents'] == ['a', 'b']
    assert asyncio.run(_client('tei', tei).rerank('q', ['a'])) == [(0, 0.7)] and seen['tei'][1] == {'query': 'q', 'texts': ['a']}
    assert asyncio.run(_client('dashscope', dash).rerank('q', ['a'])) == [(0, 0.6)]
    assert seen['dash'][0].endswith('/text-rerank') and seen['dash'][1]['input']['query'] == 'q'


def test_client_reports_bad_responses():
    with pytest.raises(RerankError):
        asyncio.run(_client('cohere', lambda r: httpx.Response(500, text='boom')).rerank('q', ['a']))
    with pytest.raises(RerankError):
        asyncio.run(_client('cohere', lambda r: httpx.Response(200, json={'results': [{'index': 9, 'relevance_score': 1}]})
                            ).rerank('q', ['a']))


class FakeReranker:
    mode = 'ok'

    async def rerank(self, query, documents):
        if FakeReranker.mode == 'error':
            raise RuntimeError('provider down')
        # Prefer the document that mentions 紧急: the opposite of keyword order.
        return [(i, 0.95 if '紧急' in d else 0.3) for i, d in enumerate(documents)]

    async def close(self):
        pass


@pytest.fixture
def rerank_env(env, monkeypatch):
    factory, tenant_id, _, owner, member, _ = env
    monkeypatch.setattr(service, '_authorize_model_of_type', lambda *args: None)
    FakeReranker.mode = 'ok'
    platform_rerank.set_reranker_factory(lambda *a: FakeReranker())
    from uuid import uuid4
    settings = {'rerank_config': {'enabled': True, 'model_id': str(uuid4()), 'threshold': 0.2}}
    kb_id = create_kb(factory, tenant_id, owner, name='重排', settings=settings)
    upload(factory, tenant_id, owner, kb_id, '普通.md', '处理故障 流程说明 处理故障 处理故障'.encode())
    upload(factory, tenant_id, owner, kb_id, '紧急.md', '处理故障 紧急联系人'.encode())
    drain(factory)
    yield factory, tenant_id, member
    platform_rerank.set_reranker_factory(None)


def test_search_reorders_with_the_rerank_model_and_reports_diagnostics(rerank_env):
    factory, tenant_id, member = rerank_env
    import asyncio as aio
    from nexus_platform.knowledge import search
    with factory() as db:
        plain = aio.run(search.search(factory, db, tenant_id, member, '处理故障', rerank=False))
        reranked = aio.run(search.search(factory, db, tenant_id, member, '处理故障'))
    assert [h.filename for h in plain.hits][0] == '普通.md' and plain.rerank is None
    assert [h.filename for h in reranked.hits][0] == '紧急.md'
    assert reranked.rerank['outcome'] == 'ok' and reranked.hits[0].ranks['rerank'] == 1 and reranked.hits[0].score > 0.6


def test_a_failing_or_missing_rerank_model_keeps_the_retrieval_order(rerank_env):
    factory, tenant_id, member = rerank_env
    import asyncio as aio
    from nexus_platform.knowledge import search
    FakeReranker.mode = 'error'
    with factory() as db:
        result = aio.run(search.search(factory, db, tenant_id, member, '处理故障'))
    assert result.rerank['outcome'] == 'model_error' and [h.filename for h in result.hits][0] == '普通.md'
    platform_rerank.set_reranker_factory(None)
    with factory() as db:
        result = aio.run(search.search(factory, db, tenant_id, member, '处理故障'))
    assert result.rerank['outcome'] == 'no_model' and len(result.hits) == 2

    def forbidden(*args):
        raise PermissionError('not allowed')
    platform_rerank.set_reranker_factory(forbidden)
    with factory() as db:
        result = aio.run(search.search(factory, db, tenant_id, member, '处理故障'))
    assert result.rerank['outcome'] == 'model_unavailable'


def test_rerank_settings_are_validated(env, monkeypatch):
    factory, tenant_id, _, owner, member, _ = env
    monkeypatch.setattr(service, '_authorize_model_of_type', lambda *args: None)
    with factory() as db, db.begin():
        with pytest.raises(ValueError, match='rerank model'):
            service.create_base(db, tenant_id, owner, visibility='tenant', name='a', indexing={'vector': False, 'keyword': True},
                                settings={'rerank_config': {'enabled': True}})
        with pytest.raises(ValueError, match='threshold'):
            service.create_base(db, tenant_id, owner, visibility='tenant', name='b', indexing={'vector': False, 'keyword': True},
                                settings={'rerank_config': {'enabled': True, 'model_id': 'x', 'threshold': 3}})
