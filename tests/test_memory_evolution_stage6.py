"""Memory evolution stage 6: interest topics and external memory providers
(openspec 2026-11-06-memory-evolution, D4 and D6; D5 waits for knowledge retrieval).
"""
import time
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from nexus_core.platform import utc_now
from nexus_memory import capture as capture_rules
from nexus_memory import service
from nexus_platform.memory import interests, providers, switches
from nexus_platform.memory.repository import SqlMemoryRepository
from nexus_platform.persistence.models import (
    AuditRecord,
    MemoryDraftRecord,
    MemoryTopicStatRecord,
    MessageRecord,
    RunRecord,
    SessionMemorySnapshotRecord,
)

from test_memory_switches import _member, _prepare
from test_native_runtime import stack
from test_platform import database  # noqa: F401 (pytest fixture)


# ---------------------------------------------------------------- interests (D4)

def _observe(factory, run, topics, session_id=None):
    with factory() as db, db.begin():
        return interests.observe(db, tenant_id=run.tenant_id, owner_id=run.principal_id,
                                 session_id=session_id or uuid4(), run_id=run.id, topics=topics)


def test_a_topic_seen_in_three_conversations_becomes_an_interest_draft_once(database):  # noqa: F811
    _, tenant, session, run, _ = stack(database)
    same = uuid4()
    assert _observe(database, run, ['部署流程', '部署 流程'], same) == []      # one conversation counts once
    assert _observe(database, run, ['部署流程'], same) == []
    assert _observe(database, run, ['部署流程！'], uuid4()) == []
    assert _observe(database, run, ['部署流程'], uuid4()) == ['部署流程']
    assert _observe(database, run, ['部署流程'], uuid4()) == []               # promoted only once
    with database() as db:
        draft = db.scalar(select(MemoryDraftRecord).where(MemoryDraftRecord.kind == 'interest'))
        assert draft.diff == '长期关注：部署流程' and draft.status == 'pending_review' and draft.origin == 'capture'
        stat = db.scalar(select(MemoryTopicStatRecord))
        assert stat.hits == 4 and stat.aliases == ['部署流程！']


def test_rejected_topics_stop_counting_and_the_threshold_is_per_space(database):  # noqa: F811
    principal, tenant, session, run, _ = stack(database)
    with database() as db:
        switches.set_space_settings(db, principal, tenant.id, enabled=True, write_mode='auto', interest_threshold=2)
    with database() as db, pytest.raises(ValueError):
        switches.set_space_settings(db, principal, tenant.id, enabled=True, write_mode='auto', interest_threshold=11)
    _observe(database, run, ['周报'])
    assert _observe(database, run, ['周报']) == ['周报']
    with database() as db, db.begin():
        draft = db.scalar(select(MemoryDraftRecord).where(MemoryDraftRecord.kind == 'interest'))
        service.review(SqlMemoryRepository(db), run.principal_id, tenant.id, draft.id, approve=False, title='')
    with database() as db, db.begin():
        db.query(MemoryTopicStatRecord).delete()
    assert _observe(database, run, ['周报']) == [] and _observe(database, run, ['周报']) == []
    with database() as db:
        assert db.scalar(select(MemoryTopicStatRecord)) is None


def test_extractors_cannot_add_interests_directly():
    verdict = capture_rules.validate_actions([{'op': 'add', 'kind': 'interest', 'diff': 'x'}], unattended=True)
    assert verdict.actions == [] and verdict.reasons == ['bad_kind']


def test_interest_entries_join_per_turn_recall():
    from test_memory_rules import FakeRepo
    repo, ws, owner = FakeRepo(), uuid4(), uuid4()
    repo.run_owner = owner
    outcome = service.propose(repo, ws, owner, uuid4(), 'interest', '长期关注：部署流程', topic='部署流程')
    entry = service.review(repo, owner, ws, UUID(outcome['id']), approve=True, title='部署流程')['id']
    assert [item['id'] for item in service.recall(repo, ws, owner, '部署流程有什么要注意').entries] == [entry]


# ---------------------------------------------------------------- providers (D6)

class FakeProvider:
    name = 'fake'

    def __init__(self, *, fail=False, slow=0.0):
        self.fail, self.slow, self.synced = fail, slow, []

    def snapshot_block(self, ctx):
        self._maybe_fail()
        return '用户在 <b>上海</b> 工作'

    def prefetch(self, ctx, query):
        self._maybe_fail()
        return f'与“{query[:10]}”相关的外部资料'

    def sync_turn(self, ctx, user, assistant):
        self._maybe_fail()
        self.synced.append((user, assistant, ctx.propose('memory', '外部服务记下的偏好', topic='外部')))

    def _maybe_fail(self):
        if self.slow:
            time.sleep(self.slow)
        if self.fail:
            raise RuntimeError('provider down')


@pytest.fixture
def provider():
    fake = FakeProvider()
    providers.register(fake)
    yield fake
    providers.unregister('fake')


def _choose(factory, principal, tenant_id, name):
    with factory() as db:
        return switches.set_space_settings(db, principal, tenant_id, enabled=True, write_mode='auto', memory_provider=name)


def test_only_registered_providers_can_be_chosen(database, provider):  # noqa: F811
    principal, tenant, session, run, _ = stack(database)
    with database() as db, pytest.raises(ValueError):
        switches.set_space_settings(db, principal, tenant.id, enabled=True, write_mode='auto', memory_provider='mem0')
    assert _choose(database, principal, tenant.id, 'fake')['memory_provider'] == 'fake'
    with pytest.raises(ValueError):
        providers.register(type('B', (), {'name': 'builtin'})())


def test_provider_text_is_fenced_into_the_snapshot_and_this_turn(database, provider):  # noqa: F811
    principal, tenant, session, run, _ = stack(database)
    _choose(database, principal, tenant.id, 'fake')
    context, _ = _prepare(database)
    system = context.messages[0].content
    assert '<user_memory source="provider:fake">' in system and '用户在 &lt;b&gt;上海&lt;/b&gt; 工作' in system
    assert context.messages[-2].content.startswith('<user_memory source="provider:fake">')
    assert context.messages[-1].role == 'user'
    with database() as db:
        assert 'provider:fake' in db.get(SessionMemorySnapshotRecord, session.id).index_text


def test_failing_providers_are_skipped_audited_and_paused(database):  # noqa: F811
    principal, tenant, session, run, _ = stack(database)
    broken = FakeProvider(fail=True)
    providers.register(broken)
    try:
        for _ in range(providers.STALL_LIMIT):
            assert providers.prefetch_text(database, broken, tenant_id=tenant.id, owner_id=run.principal_id,
                                           session_id=session.id, query='x') == ''
        _choose(database, principal, tenant.id, 'fake')
        with database() as db:
            assert providers.provider_for(db, tenant.id) is None               # paused after three failures
            assert db.query(AuditRecord).filter(AuditRecord.action == 'memory.provider_failed').count() == 3
    finally:
        providers.unregister('fake')
    slow = FakeProvider(slow=0.3)
    providers.register(slow)
    try:
        assert providers.call(slow, 'prefetch', lambda: slow.prefetch(None, 'q'), timeout=0.05) is None
    finally:
        providers.unregister('fake')


def test_after_run_syncs_the_turn_and_provider_writes_become_drafts(database, provider):  # noqa: F811
    principal, tenant, session, run, _ = stack(database)
    _choose(database, principal, tenant.id, 'fake')
    with database() as db, db.begin():
        db.get(RunRecord, run.id).status = 'completed'
        db.add(MessageRecord(id=uuid4(), session_id=session.id, run_id=run.id, sequence=50, role='assistant',
                             content='好的', runtime_metadata={}, created_at=utc_now()))
    thread = providers.after_run(database, run.id)
    thread.join(5)
    (user, assistant, outcome), = provider.synced
    assert assistant == '好的' and outcome.startswith('pending: ')
    with database() as db:
        draft = db.scalar(select(MemoryDraftRecord).where(MemoryDraftRecord.origin == 'background'))
        assert draft.diff == '外部服务记下的偏好' and draft.status == 'pending_review'
    _member(database, principal, tenant.id, False)
    assert providers.after_run(database, run.id) is None                     # memory off: no hook


def test_migration_adds_and_removes_stage6_schema(tmp_path):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, inspect
    url = f'sqlite:///{tmp_path / "m6.db"}'
    config = Config('alembic.ini')
    config.attributes['database_url'] = url
    command.upgrade(config, 'a9b8c7d6e5f4')
    inspector = inspect(create_engine(url))
    assert 'memory_topic_stats' in inspector.get_table_names()
    assert {'interest_threshold', 'memory_provider'} <= {c['name'] for c in inspector.get_columns('memory_space_settings')}
    command.downgrade(config, 'f1a2b3c4d5e6')
    assert 'memory_topic_stats' not in inspect(create_engine(url)).get_table_names()
