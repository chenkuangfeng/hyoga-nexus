"""Memory evolution stage 5: semantic recall, per-turn recall, capture usage (openspec 2026-11-06-memory-evolution).

Rules: cosine / nearest / reciprocal-rank fusion, search fused with a vector ranking, per-turn recall.
Platform: the space embedding model is validated, the worker tick stores vectors with an injected embedder,
memory search uses them and degrades to keywords, preparation injects recall before the last user message
without touching the system prefix, the agent can turn recall off, and capture usage is summed.
"""
import asyncio
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from nexus_core.platform import utc_now
from nexus_memory import capture as capture_rules
from nexus_memory import semantic, service
from nexus_memory import switches as switch_rules
from nexus_platform.memory import capture, switches, vectors
from nexus_platform.memory.repository import SqlMemoryRepository
from nexus_platform.models.service import create_model_profile
from nexus_platform.persistence.models import (
    MemoryCaptureJobRecord,
    MemoryEmbeddingRecord,
    MessageRecord,
    ModelProfileRecord,
)
from nexus_platform.persistence.models.event import RunEventRecord
from nexus_platform.runs.store import DurableRuntimeStore

from test_memory_capture import _enable, _enqueue
from test_memory_rules import FakeRepo
from test_memory_switches import _prepare
from test_native_runtime import stack
from test_platform import database  # noqa: F401 (pytest fixture)

TOOLS = sorted(switch_rules.MEMORY_TOOL_NAMES)


# ---------------------------------------------------------------- rules

def test_cosine_nearest_and_fusion():
    a, b, c = uuid4(), uuid4(), uuid4()
    assert semantic.cosine([1, 0], [1, 0]) == pytest.approx(1.0) and semantic.cosine([1, 0], [0, 1]) == 0
    assert semantic.cosine([], []) == 0 and semantic.cosine([1], [1, 2]) == 0
    assert semantic.nearest([1, 0], [(a, [0.9, 0.1]), (b, [0, 1]), (c, [1, 0])]) == [c, a]
    assert semantic.fuse([a, b], [b, c]) == [b, a, c]
    assert semantic.embeddable_text('语言', '偏好 Python') == '语言：偏好 Python'
    assert semantic.embeddable_text('Python', '偏好 Python') == '偏好 Python'


@pytest.fixture
def world():
    repo = FakeRepo()
    ws, owner = uuid4(), uuid4()
    repo.run_owner = owner
    return repo, ws, owner


def _publish(repo, ws, owner, diff, *, title, kind='memory'):
    outcome = service.propose(repo, ws, owner, uuid4(), kind, diff)
    return service.review(repo, owner, ws, UUID(outcome['id']), approve=True, title=title)['id']


def test_search_fuses_vector_hits_including_entries_the_keywords_missed(world):
    repo, ws, owner = world
    keyword = _publish(repo, ws, owner, 'deploy with the release checklist', title='Deploy')
    semantic_only = _publish(repo, ws, owner, '上线前要逐项核对', title='上线核对')
    hits = service.search(repo, ws, owner, 'release checklist', vector_ranking=[UUID(semantic_only)])
    assert [hit['id'] for hit in hits] == [keyword, semantic_only]
    # A vector hit on an archived entry is ignored.
    service.archive(repo, owner, ws, UUID(semantic_only))
    assert [hit['id'] for hit in service.search(repo, ws, owner, 'release checklist',
                                                vector_ranking=[UUID(semantic_only)])] == [keyword]


def test_recall_picks_relevant_memory_within_bounds_and_skips_resident_and_other_kinds(world):
    repo, ws, owner = world
    deploy = _publish(repo, ws, owner, '部署前跑发布检查清单', title='部署')
    _publish(repo, ws, owner, '部署流程：构建、发布、验证', title='部署流程', kind='sop')
    resident = _publish(repo, ws, owner, '部署时偏好中文提示', title='风格', kind='profile')
    _publish(repo, ws, owner, '周报周五发', title='周报')
    result = service.recall(repo, ws, owner, '今天要部署，检查清单在哪', exclude=frozenset({resident}))
    assert [item['id'] for item in result.entries] == [deploy]
    assert result.text.startswith('<user_memory source="recall">') and '- [部署] 部署前跑发布检查清单' in result.text
    assert service.recall(repo, ws, owner, '天气怎么样').text == ''
    [_publish(repo, ws, owner, f'部署注意事项 {n} ' + '细节' * 40, title=f'注意 {n}') for n in range(8)]
    bounded = service.recall(repo, ws, owner, '部署注意事项')
    assert len(bounded.entries) <= service.RECALL_MAX_ITEMS
    assert sum(len(repo.versions[(UUID(e['id']), 1)].content) for e in bounded.entries) <= service.RECALL_MAX_CHARS



def test_agent_recall_budget_is_validated():
    switch_rules.validate_agent_budget({'memory': {'enabled': True, 'recall': False}})
    with pytest.raises(ValueError):
        switch_rules.validate_agent_budget({'memory': {'recall': 'no'}})
    assert switch_rules.recall_enabled(None) and not switch_rules.recall_enabled({'memory': {'recall': False}})


# ---------------------------------------------------------------- platform

def _publish_db(factory, run, text, *, title, kind='memory'):
    with factory() as db, db.begin():
        repo = SqlMemoryRepository(db)
        outcome = service.propose(repo, run.tenant_id, run.principal_id, run.id, kind, text)
        return service.review(repo, run.principal_id, run.tenant_id, UUID(outcome['id']), approve=True, title=title)['id']


def _embedding_model(factory, principal, tenant_id):
    with factory() as db:
        profile, version = create_model_profile(db, principal, tenant_id, name='embed', provider='test',
                                                model_name='fake-embedding', options={})
    with factory() as db, db.begin():
        db.get(ModelProfileRecord, profile.id).model_type = 'embedding'
    return version.id


class FakeEmbedder:
    """Two-dimensional vectors: texts about deployment point one way, everything else the other."""
    calls: list = []

    async def embed(self, texts):
        FakeEmbedder.calls.append(list(texts))
        return [[1.0, 0.0] if ('部署' in t or '上线' in t or 'release' in t) else [0.0, 1.0] for t in texts]

    async def close(self):
        pass


@pytest.fixture
def embedder():
    FakeEmbedder.calls = []
    vectors.reset_failures()
    vectors.set_embedder_factory(lambda factory, tenant, owner, model: FakeEmbedder())
    yield FakeEmbedder
    vectors.set_embedder_factory(None)


def test_space_embedding_model_must_be_an_embedding_model(database):  # noqa: F811
    principal, tenant, session, run, _ = stack(database)
    model_id = _embedding_model(database, principal, tenant.id)
    with database() as db:
        view = switches.set_space_settings(db, principal, tenant.id, enabled=True, write_mode='auto',
                                           embedding_model_version_id=model_id)
    assert view['embedding_model_version_id'] == str(model_id)
    with database() as db:
        _, chat = create_model_profile(db, principal, tenant.id, name='chat', provider='test', model_name='c', options={})
    with database() as db, pytest.raises(ValueError):
        switches.set_space_settings(db, principal, tenant.id, enabled=True, write_mode='auto',
                                    embedding_model_version_id=chat.id)
    with database() as db:
        switches.set_space_settings(db, principal, tenant.id, enabled=True, write_mode='auto')
        assert switches.space_settings(db, principal, tenant.id)['embedding_model_version_id'] == str(model_id)


def test_worker_tick_embeds_current_versions_and_search_uses_them(database, embedder):  # noqa: F811
    principal, tenant, session, run, _ = stack(database, TOOLS)
    model_id = _embedding_model(database, principal, tenant.id)
    with database() as db:
        switches.set_space_settings(db, principal, tenant.id, enabled=True, write_mode='auto',
                                    embedding_model_version_id=model_id)
    target = _publish_db(database, run, '上线前要逐项核对', title='上线核对')
    _publish_db(database, run, '周报周五发', title='周报')
    assert asyncio.run(vectors.embedding_tick(database)) == 2
    assert asyncio.run(vectors.embedding_tick(database)) == 0          # nothing left to embed
    context, task = _prepare(database)
    store = DurableRuntimeStore(database, context, 'memory-worker', task)
    found = asyncio.run(store.search_memory('release 流程', 5))
    assert found.startswith(f'[{target}]')                            # no keyword overlap: the vector found it
    with database() as db:
        row = db.scalar(select(MemoryEmbeddingRecord).where(MemoryEmbeddingRecord.entry_id == UUID(target)))
        assert row.model_version_id == model_id and row.dims == 2


def test_search_degrades_to_keywords_when_embedding_fails(database):  # noqa: F811
    principal, tenant, session, run, _ = stack(database, TOOLS)
    model_id = _embedding_model(database, principal, tenant.id)
    with database() as db:
        switches.set_space_settings(db, principal, tenant.id, enabled=True, write_mode='auto',
                                    embedding_model_version_id=model_id)
    entry = _publish_db(database, run, 'deploy with the release checklist', title='Deploy')
    vectors.set_embedder_factory(lambda factory, tenant, owner, model: FakeEmbedder())
    try:
        asyncio.run(vectors.embedding_tick(database))

        def broken(factory, tenant, owner, model):
            raise RuntimeError('provider down')
        vectors.set_embedder_factory(broken)
        context, task = _prepare(database)
        store = DurableRuntimeStore(database, context, 'memory-worker', task)
        assert asyncio.run(store.search_memory('release checklist', 5)).startswith(f'[{entry}]')
    finally:
        vectors.set_embedder_factory(None)


def test_preparation_injects_recall_before_the_last_user_message_only(database):  # noqa: F811
    _, tenant, session, run, _ = stack(database, TOOLS)
    with database() as db:
        question = db.scalar(select(MessageRecord.content).where(MessageRecord.session_id == session.id))
    entry = _publish_db(database, run, f'关于 {question} 的已审核结论', title='结论')
    context, _ = _prepare(database)
    messages = list(context.messages)
    recall_index = next(i for i, m in enumerate(messages) if m.content.startswith('<user_memory source="recall">'))
    assert messages[recall_index + 1].role == 'user' and messages[recall_index + 1].content == question
    assert recall_index == len(messages) - 2
    assert '<user_memory source="recall">' not in messages[0].content
    with database() as db:
        used = [row.payload for row in db.scalars(select(RunEventRecord).where(
            RunEventRecord.run_id == run.id, RunEventRecord.event_type == 'memory.used'))]
    assert used == [{'source': 'recall', 'entries': [{'id': entry, 'title': '结论', 'kind': 'memory', 'version': 1}]}]


def test_agent_can_turn_recall_off(database):  # noqa: F811
    budgets = {'max_tokens': 100000, 'memory': {'recall': False}}
    _, tenant, session, run, _ = stack(database, TOOLS, budgets=budgets)
    with database() as db:
        question = db.scalar(select(MessageRecord.content).where(MessageRecord.session_id == session.id))
    _publish_db(database, run, f'关于 {question} 的已审核结论', title='结论')
    context, _ = _prepare(database)
    assert not any(m.content.startswith('<user_memory source="recall">') for m in context.messages)


def test_capture_usage_is_recorded_and_summed(database):  # noqa: F811
    principal, tenant, session, run, _ = stack(database)
    _enable(database, principal, tenant.id)
    _enqueue(database, run.id, utc_now())

    def extractor(**kwargs):
        return capture_rules.ExtractorReply([], {'input_tokens': 120, 'output_tokens': 8})
    capture.run_due(database, extractor, worker_id='w1', now=utc_now() + timedelta(hours=1))
    with database() as db:
        assert db.scalar(select(MemoryCaptureJobRecord.usage)) == {'input_tokens': 120, 'output_tokens': 8}
    with database() as db:
        assert capture.capture_usage(db, principal, tenant.id) == {
            'days': 30, 'calls': 1, 'usage': {'input_tokens': 120, 'output_tokens': 8}}


def test_migration_adds_and_removes_stage5_schema(tmp_path):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, inspect
    url = f'sqlite:///{tmp_path / "m5.db"}'
    config = Config('alembic.ini')
    config.attributes['database_url'] = url
    command.upgrade(config, 'f1a2b3c4d5e6')
    inspector = inspect(create_engine(url))
    assert 'memory_embeddings' in inspector.get_table_names()
    assert 'embedding_model_version_id' in {c['name'] for c in inspector.get_columns('memory_space_settings')}
    assert 'usage' in {c['name'] for c in inspector.get_columns('memory_capture_jobs')}
    command.downgrade(config, 'e8f4c6b1d3a5')
    assert 'memory_embeddings' not in inspect(create_engine(url)).get_table_names()
